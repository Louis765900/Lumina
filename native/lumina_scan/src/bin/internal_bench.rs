use std::{
    fs::File,
    io::{self, BufReader, Read, Write},
    path::PathBuf,
    time::{Duration, Instant},
};

use aho_corasick::{AhoCorasick, AhoCorasickBuilder, MatchKind};
use lumina_scan::{
    control::StopControl,
    prefix_matcher::PrefixMatcher,
    protocol::{
        CandidateItem, CandidatesEvent, FinishedEvent, ProgressEvent, ScanCommand, ScanEvent,
        SignatureSpec, SourceSpec,
    },
    scanner::scan_image,
};
use serde::Serialize;

const CHUNK_SIZES_MB: [usize; 3] = [16, 32, 64];
const BATCH_SIZES: [usize; 3] = [512, 2048, 8192];
const PROGRESS_INTERVALS_MS: [u64; 2] = [250, 1000];
const PROFILE_BATCH_SIZE: usize = 8192;
const PROFILE_PROGRESS_INTERVAL_MS: u64 = 1000;

#[derive(Debug, Clone)]
struct BenchSignature {
    signature_id: &'static str,
    ext: &'static str,
    header: &'static [u8],
}

#[derive(Debug, Serialize)]
struct BenchReport {
    image: String,
    size_bytes: u64,
    signatures: usize,
    read_only: Vec<BenchResult>,
    scan_overlapping_no_jsonl: Vec<BenchResult>,
    scan_leftmost_no_jsonl: Vec<BenchResult>,
    scan_overlapping_no_copy_no_jsonl: Vec<BenchResult>,
    scan_leftmost_no_copy_no_jsonl: Vec<BenchResult>,
    scan_prefix_u32_no_jsonl: Vec<BenchResult>,
    scan_prefix_u32_no_copy_no_jsonl: Vec<BenchResult>,
    scan_prefix_u32_jsonl_simulated: Vec<JsonlBenchResult>,
    scan_jsonl_batched: Vec<JsonlBenchResult>,
}

#[derive(Debug, Serialize)]
struct BenchResult {
    chunk_size_mb: usize,
    duration_ms: u128,
    mbps: f64,
    candidates: u64,
}

#[derive(Debug, Serialize)]
struct JsonlBenchResult {
    chunk_size_mb: usize,
    candidate_batch_size: usize,
    progress_interval_ms: u64,
    duration_ms: u128,
    mbps: f64,
    candidates: u64,
    events: u64,
}

#[derive(Debug, Serialize)]
struct ProfileReport {
    image: String,
    size_bytes: u64,
    signatures: usize,
    candidate_batch_size: usize,
    progress_interval_ms: u64,
    runs: Vec<ProfileRun>,
}

#[derive(Debug, Serialize)]
struct ProfileRun {
    matcher: &'static str,
    chunk_size_mb: usize,
    copy_overlap_into_scan_buffer: bool,
    jsonl_enabled: bool,
    duration_ms: u128,
    mbps: f64,
    candidates: u64,
    events: u64,
    chunks: u64,
    bytes_read: u64,
    bytes_copied: u64,
    timing: ProfileTimingReport,
}

#[derive(Debug, Serialize)]
struct ProfileTimingReport {
    read: ProfileTimingBucket,
    buffer_overlap: ProfileTimingBucket,
    matching: ProfileTimingBucket,
    batching: ProfileTimingBucket,
    jsonl_stdout: ProfileTimingBucket,
    unaccounted: ProfileTimingBucket,
}

#[derive(Debug, Serialize)]
struct ProfileTimingBucket {
    ns: u128,
    ms: f64,
    percent: f64,
}

#[derive(Debug, Default)]
struct ProfileCounters {
    read_ns: u128,
    buffer_ns: u128,
    matching_ns: u128,
    batching_ns: u128,
    jsonl_ns: u128,
    chunks: u64,
    bytes_read: u64,
    bytes_copied: u64,
    candidates: u64,
    events: u64,
}

#[derive(Debug, Clone, Copy)]
struct FoundCandidate {
    absolute_offset: u64,
    pattern_id: usize,
    buffer_start: usize,
    buffer_end: usize,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let options = parse_options()?;
    let image = options.image;
    let size_bytes = std::fs::metadata(&image)?.len();
    let signatures = bench_signatures();
    let patterns = patterns_by_python_priority(&signatures);

    if options.profile_breakdown {
        let report = profile_breakdown_report(&image, size_bytes, &signatures)?;
        serde_json::to_writer_pretty(io::stdout(), &report)?;
        println!();
        return Ok(());
    }

    let mut report = BenchReport {
        image: image.to_string_lossy().to_string(),
        size_bytes,
        signatures: signatures.len(),
        read_only: Vec::new(),
        scan_overlapping_no_jsonl: Vec::new(),
        scan_leftmost_no_jsonl: Vec::new(),
        scan_overlapping_no_copy_no_jsonl: Vec::new(),
        scan_leftmost_no_copy_no_jsonl: Vec::new(),
        scan_prefix_u32_no_jsonl: Vec::new(),
        scan_prefix_u32_no_copy_no_jsonl: Vec::new(),
        scan_prefix_u32_jsonl_simulated: Vec::new(),
        scan_jsonl_batched: Vec::new(),
    };

    for chunk_mb in CHUNK_SIZES_MB {
        let chunk_size = chunk_mb * 1024 * 1024;
        report
            .read_only
            .push(read_only(&image, size_bytes, chunk_mb, chunk_size)?);
        report.scan_overlapping_no_jsonl.push(scan_no_jsonl(
            &image,
            size_bytes,
            chunk_mb,
            chunk_size,
            &patterns,
            MatcherMode::Overlapping,
        )?);
        report.scan_leftmost_no_jsonl.push(scan_no_jsonl(
            &image,
            size_bytes,
            chunk_mb,
            chunk_size,
            &patterns,
            MatcherMode::LeftmostFirst,
        )?);
        report
            .scan_overlapping_no_copy_no_jsonl
            .push(scan_no_copy_no_jsonl(
                &image,
                size_bytes,
                chunk_mb,
                chunk_size,
                &patterns,
                MatcherMode::Overlapping,
            )?);
        report
            .scan_leftmost_no_copy_no_jsonl
            .push(scan_no_copy_no_jsonl(
                &image,
                size_bytes,
                chunk_mb,
                chunk_size,
                &patterns,
                MatcherMode::LeftmostFirst,
            )?);
        report.scan_prefix_u32_no_jsonl.push(scan_prefix_no_jsonl(
            &image,
            size_bytes,
            chunk_mb,
            chunk_size,
            &signatures,
            true,
        )?);
        report
            .scan_prefix_u32_no_copy_no_jsonl
            .push(scan_prefix_no_jsonl(
                &image,
                size_bytes,
                chunk_mb,
                chunk_size,
                &signatures,
                false,
            )?);
    }

    for chunk_mb in CHUNK_SIZES_MB {
        for batch_size in BATCH_SIZES {
            for progress_interval_ms in PROGRESS_INTERVALS_MS {
                report.scan_jsonl_batched.push(scan_jsonl(
                    &image,
                    size_bytes,
                    &signatures,
                    chunk_mb,
                    chunk_mb * 1024 * 1024,
                    batch_size,
                    progress_interval_ms,
                )?);
                report
                    .scan_prefix_u32_jsonl_simulated
                    .push(scan_prefix_jsonl(
                        &image,
                        size_bytes,
                        &signatures,
                        chunk_mb,
                        chunk_mb * 1024 * 1024,
                        batch_size,
                        progress_interval_ms,
                    )?);
            }
        }
    }

    serde_json::to_writer_pretty(io::stdout(), &report)?;
    println!();
    Ok(())
}

struct CliOptions {
    image: PathBuf,
    profile_breakdown: bool,
}

fn parse_options() -> Result<CliOptions, String> {
    let mut args = std::env::args().skip(1);
    let mut image = None;
    let mut profile_breakdown = false;

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--image" => {
                image = Some(
                    args.next()
                        .map(PathBuf::from)
                        .ok_or_else(|| "--image requires a path".to_string())?,
                );
            }
            "--profile-breakdown" => {
                profile_breakdown = true;
            }
            _ => {
                return Err(format!(
                    "unknown argument {arg}; usage: internal_bench --image <path> [--profile-breakdown]"
                ));
            }
        }
    }

    Ok(CliOptions {
        image: image.ok_or_else(|| {
            "usage: internal_bench --image <path> [--profile-breakdown]".to_string()
        })?,
        profile_breakdown,
    })
}

fn bench_signatures() -> Vec<BenchSignature> {
    vec![
        BenchSignature {
            signature_id: "gif_474946383761",
            ext: ".gif",
            header: b"GIF87a",
        },
        BenchSignature {
            signature_id: "jpg_ffd8ffc0",
            ext: ".jpg",
            header: b"\xff\xd8\xff\xc0",
        },
        BenchSignature {
            signature_id: "pdf_255044462d",
            ext: ".pdf",
            header: b"%PDF-",
        },
        BenchSignature {
            signature_id: "png_89504e470d0a1a0a",
            ext: ".png",
            header: b"\x89PNG\r\n\x1a\n",
        },
        BenchSignature {
            signature_id: "zip_504b0304",
            ext: ".zip",
            header: b"PK\x03\x04",
        },
    ]
}

fn patterns_by_python_priority(signatures: &[BenchSignature]) -> Vec<&[u8]> {
    let mut patterns: Vec<&[u8]> = signatures.iter().map(|sig| sig.header).collect();
    patterns.sort_by_key(|pattern| std::cmp::Reverse(pattern.len()));
    patterns
}

fn read_only(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
) -> io::Result<BenchResult> {
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let started = Instant::now();
    let mut bytes_read = 0u64;

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }
        bytes_read += read_len as u64;
    }

    Ok(result(
        chunk_size_mb,
        started.elapsed(),
        size_bytes,
        bytes_read,
    ))
}

fn profile_breakdown_report(
    image: &PathBuf,
    size_bytes: u64,
    signatures: &[BenchSignature],
) -> Result<ProfileReport, Box<dyn std::error::Error>> {
    let ordered_signatures = signatures_by_python_priority(signatures);
    let mut runs = Vec::new();

    for chunk_mb in CHUNK_SIZES_MB {
        let chunk_size = chunk_mb * 1024 * 1024;
        for mode in [MatcherMode::Overlapping, MatcherMode::LeftmostFirst] {
            for copy_overlap_into_scan_buffer in [true, false] {
                for jsonl_enabled in [false, true] {
                    runs.push(profile_aho_scan(
                        image,
                        size_bytes,
                        chunk_mb,
                        chunk_size,
                        &ordered_signatures,
                        mode,
                        copy_overlap_into_scan_buffer,
                        jsonl_enabled,
                    )?);
                }
            }
        }
    }

    Ok(ProfileReport {
        image: image.to_string_lossy().to_string(),
        size_bytes,
        signatures: signatures.len(),
        candidate_batch_size: PROFILE_BATCH_SIZE,
        progress_interval_ms: PROFILE_PROGRESS_INTERVAL_MS,
        runs,
    })
}

fn signatures_by_python_priority(signatures: &[BenchSignature]) -> Vec<&BenchSignature> {
    let mut ordered: Vec<&BenchSignature> = signatures.iter().collect();
    ordered.sort_by_key(|sig| std::cmp::Reverse(sig.header.len()));
    ordered
}

fn profile_aho_scan(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    signatures: &[&BenchSignature],
    mode: MatcherMode,
    copy_overlap_into_scan_buffer: bool,
    jsonl_enabled: bool,
) -> Result<ProfileRun, Box<dyn std::error::Error>> {
    let patterns: Vec<&[u8]> = signatures.iter().map(|sig| sig.header).collect();
    let matcher = build_aho(&patterns, mode)?;
    let overlap_size = patterns
        .iter()
        .map(|pattern| pattern.len())
        .max()
        .unwrap_or(1)
        .saturating_sub(1);
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut scan_buf = Vec::<u8>::with_capacity(chunk_size + overlap_size);
    let mut boundary = Vec::<u8>::with_capacity(overlap_size * 2);
    let mut counters = ProfileCounters::default();
    let mut sink = io::sink();
    let mut batch = Vec::<CandidateItem>::with_capacity(PROFILE_BATCH_SIZE);
    let mut batch_index = 0u64;
    let progress_interval = Duration::from_millis(PROFILE_PROGRESS_INTERVAL_MS);
    let started = Instant::now();
    let mut last_progress = started;

    loop {
        let read_started = Instant::now();
        let read_len = reader.read(&mut chunk)?;
        counters.read_ns += duration_ns(read_started.elapsed());
        if read_len == 0 {
            break;
        }

        counters.chunks += 1;
        let bytes_before_chunk = counters.bytes_read;
        counters.bytes_read += read_len as u64;

        if copy_overlap_into_scan_buffer {
            let buffer_started = Instant::now();
            let overlap_len = overlap.len();
            let data_offset = bytes_before_chunk.saturating_sub(overlap_len as u64);
            scan_buf.clear();
            scan_buf.extend_from_slice(&overlap);
            scan_buf.extend_from_slice(&chunk[..read_len]);
            counters.bytes_copied += (overlap_len + read_len) as u64;
            counters.buffer_ns += duration_ns(buffer_started.elapsed());

            let matching_started = Instant::now();
            let matches =
                collect_matches(&matcher, &scan_buf, mode, Some(overlap_len), data_offset);
            counters.matching_ns += duration_ns(matching_started.elapsed());
            consume_profile_matches(
                matches,
                signatures,
                jsonl_enabled,
                &mut counters,
                &mut sink,
                &mut batch,
                &mut batch_index,
            )?;

            let buffer_started = Instant::now();
            if overlap_size > 0 {
                let keep = overlap_size.min(scan_buf.len());
                overlap.clear();
                overlap.extend_from_slice(&scan_buf[scan_buf.len() - keep..]);
                counters.bytes_copied += keep as u64;
            }
            counters.buffer_ns += duration_ns(buffer_started.elapsed());
        } else {
            let overlap_len = overlap.len();
            if overlap_len > 0 {
                let buffer_started = Instant::now();
                let prefix_len = overlap_size.min(read_len);
                boundary.clear();
                boundary.extend_from_slice(&overlap);
                boundary.extend_from_slice(&chunk[..prefix_len]);
                counters.bytes_copied += (overlap_len + prefix_len) as u64;
                counters.buffer_ns += duration_ns(buffer_started.elapsed());

                let matching_started = Instant::now();
                let boundary_matches = collect_boundary_matches(
                    &matcher,
                    &boundary,
                    mode,
                    overlap_len,
                    bytes_before_chunk.saturating_sub(overlap_len as u64),
                );
                counters.matching_ns += duration_ns(matching_started.elapsed());
                consume_profile_matches(
                    boundary_matches,
                    signatures,
                    jsonl_enabled,
                    &mut counters,
                    &mut sink,
                    &mut batch,
                    &mut batch_index,
                )?;
            }

            let matching_started = Instant::now();
            let chunk_matches =
                collect_matches(&matcher, &chunk[..read_len], mode, None, bytes_before_chunk);
            counters.matching_ns += duration_ns(matching_started.elapsed());
            consume_profile_matches(
                chunk_matches,
                signatures,
                jsonl_enabled,
                &mut counters,
                &mut sink,
                &mut batch,
                &mut batch_index,
            )?;

            let buffer_started = Instant::now();
            if overlap_size > 0 {
                let keep = overlap_size.min(read_len);
                overlap.clear();
                overlap.extend_from_slice(&chunk[read_len - keep..read_len]);
                counters.bytes_copied += keep as u64;
            }
            counters.buffer_ns += duration_ns(buffer_started.elapsed());
        }

        if jsonl_enabled && last_progress.elapsed() >= progress_interval {
            let jsonl_started = Instant::now();
            if flush_profile_batch(&mut sink, &mut batch, &mut batch_index)? {
                counters.events += 1;
            }
            write_profile_progress(
                &mut sink,
                counters.bytes_read,
                size_bytes,
                started.elapsed(),
            )?;
            counters.events += 1;
            counters.jsonl_ns += duration_ns(jsonl_started.elapsed());
            last_progress = Instant::now();
        }
    }

    if jsonl_enabled {
        let jsonl_started = Instant::now();
        if flush_profile_batch(&mut sink, &mut batch, &mut batch_index)? {
            counters.events += 1;
        }
        write_profile_progress(
            &mut sink,
            counters.bytes_read,
            size_bytes,
            started.elapsed(),
        )?;
        write_profile_finished(
            &mut sink,
            counters.bytes_read,
            counters.candidates,
            started.elapsed(),
            size_bytes,
        )?;
        counters.events += 2;
        counters.jsonl_ns += duration_ns(jsonl_started.elapsed());
    }

    let duration = started.elapsed();
    Ok(ProfileRun {
        matcher: mode.as_str(),
        chunk_size_mb,
        copy_overlap_into_scan_buffer,
        jsonl_enabled,
        duration_ms: duration.as_millis(),
        mbps: mbps(size_bytes, duration),
        candidates: counters.candidates,
        events: counters.events,
        chunks: counters.chunks,
        bytes_read: counters.bytes_read,
        bytes_copied: counters.bytes_copied,
        timing: profile_timing_report(duration, &counters),
    })
}

#[derive(Clone, Copy)]
enum MatcherMode {
    Overlapping,
    LeftmostFirst,
}

impl MatcherMode {
    fn as_str(self) -> &'static str {
        match self {
            MatcherMode::Overlapping => "aho_overlapping",
            MatcherMode::LeftmostFirst => "aho_leftmost_first",
        }
    }
}

fn scan_no_jsonl(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    patterns: &[&[u8]],
    mode: MatcherMode,
) -> Result<BenchResult, Box<dyn std::error::Error>> {
    let matcher = match mode {
        MatcherMode::Overlapping => AhoCorasick::new(patterns)?,
        MatcherMode::LeftmostFirst => AhoCorasickBuilder::new()
            .match_kind(MatchKind::LeftmostFirst)
            .build(patterns)?,
    };
    let overlap_size = patterns
        .iter()
        .map(|pattern| pattern.len())
        .max()
        .unwrap_or(1)
        .saturating_sub(1);
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut scan_buf = Vec::<u8>::with_capacity(chunk_size + overlap_size);
    let started = Instant::now();
    let mut candidates = 0u64;

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }

        let overlap_len = overlap.len();
        scan_buf.clear();
        scan_buf.extend_from_slice(&overlap);
        scan_buf.extend_from_slice(&chunk[..read_len]);

        match mode {
            MatcherMode::Overlapping => {
                for mat in matcher.find_overlapping_iter(&scan_buf) {
                    if mat.start() < overlap_len && mat.end() <= overlap_len {
                        continue;
                    }
                    candidates += 1;
                }
            }
            MatcherMode::LeftmostFirst => {
                for mat in matcher.find_iter(&scan_buf) {
                    if mat.start() < overlap_len && mat.end() <= overlap_len {
                        continue;
                    }
                    candidates += 1;
                }
            }
        }

        if overlap_size > 0 {
            let keep = overlap_size.min(scan_buf.len());
            overlap.clear();
            overlap.extend_from_slice(&scan_buf[scan_buf.len() - keep..]);
        }
    }

    Ok(result_with_candidates(
        chunk_size_mb,
        started.elapsed(),
        size_bytes,
        candidates,
    ))
}

fn scan_no_copy_no_jsonl(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    patterns: &[&[u8]],
    mode: MatcherMode,
) -> Result<BenchResult, Box<dyn std::error::Error>> {
    let matcher = match mode {
        MatcherMode::Overlapping => AhoCorasick::new(patterns)?,
        MatcherMode::LeftmostFirst => AhoCorasickBuilder::new()
            .match_kind(MatchKind::LeftmostFirst)
            .build(patterns)?,
    };
    let overlap_size = patterns
        .iter()
        .map(|pattern| pattern.len())
        .max()
        .unwrap_or(1)
        .saturating_sub(1);
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut boundary = Vec::<u8>::with_capacity(overlap_size * 2);
    let started = Instant::now();
    let mut candidates = 0u64;

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }

        let overlap_len = overlap.len();
        if overlap_len > 0 {
            let prefix_len = overlap_size.min(read_len);
            boundary.clear();
            boundary.extend_from_slice(&overlap);
            boundary.extend_from_slice(&chunk[..prefix_len]);
            candidates += count_boundary_crossing(&matcher, &boundary, overlap_len, mode);
        }

        candidates += count_matches(&matcher, &chunk[..read_len], mode);

        if overlap_size > 0 {
            let keep = overlap_size.min(read_len);
            overlap.clear();
            overlap.extend_from_slice(&chunk[read_len - keep..read_len]);
        }
    }

    Ok(result_with_candidates(
        chunk_size_mb,
        started.elapsed(),
        size_bytes,
        candidates,
    ))
}

fn scan_prefix_no_jsonl(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    signatures: &[BenchSignature],
    copy_overlap_into_scan_buffer: bool,
) -> Result<BenchResult, Box<dyn std::error::Error>> {
    let specs = signature_specs(signatures);
    let matcher = PrefixMatcher::from_specs(&specs)?;
    if copy_overlap_into_scan_buffer {
        scan_prefix_with_copy(image, size_bytes, chunk_size_mb, chunk_size, &matcher)
    } else {
        scan_prefix_no_copy(image, size_bytes, chunk_size_mb, chunk_size, &matcher)
    }
}

fn scan_prefix_with_copy(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    matcher: &PrefixMatcher,
) -> Result<BenchResult, Box<dyn std::error::Error>> {
    let overlap_size = matcher.overlap_size();
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut scan_buf = Vec::<u8>::with_capacity(chunk_size + overlap_size);
    let started = Instant::now();
    let mut candidates = 0u64;

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }

        let overlap_len = overlap.len();
        scan_buf.clear();
        scan_buf.extend_from_slice(&overlap);
        scan_buf.extend_from_slice(&chunk[..read_len]);

        for found in matcher.find_iter(&scan_buf) {
            if found.start < overlap_len && found.end <= overlap_len {
                continue;
            }
            candidates += 1;
        }

        if overlap_size > 0 {
            let keep = overlap_size.min(scan_buf.len());
            overlap.clear();
            overlap.extend_from_slice(&scan_buf[scan_buf.len() - keep..]);
        }
    }

    Ok(result_with_candidates(
        chunk_size_mb,
        started.elapsed(),
        size_bytes,
        candidates,
    ))
}

fn scan_prefix_no_copy(
    image: &PathBuf,
    size_bytes: u64,
    chunk_size_mb: usize,
    chunk_size: usize,
    matcher: &PrefixMatcher,
) -> Result<BenchResult, Box<dyn std::error::Error>> {
    let overlap_size = matcher.overlap_size();
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut boundary = Vec::<u8>::with_capacity(overlap_size * 2);
    let started = Instant::now();
    let mut candidates = 0u64;

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }

        let overlap_len = overlap.len();
        if overlap_len > 0 {
            let prefix_len = overlap_size.min(read_len);
            boundary.clear();
            boundary.extend_from_slice(&overlap);
            boundary.extend_from_slice(&chunk[..prefix_len]);
            candidates += matcher
                .find_iter(&boundary)
                .filter(|found| found.start < overlap_len && found.end > overlap_len)
                .count() as u64;
        }

        candidates += matcher.find_iter(&chunk[..read_len]).count() as u64;

        if overlap_size > 0 {
            let keep = overlap_size.min(read_len);
            overlap.clear();
            overlap.extend_from_slice(&chunk[read_len - keep..read_len]);
        }
    }

    Ok(result_with_candidates(
        chunk_size_mb,
        started.elapsed(),
        size_bytes,
        candidates,
    ))
}

fn scan_prefix_jsonl(
    image: &PathBuf,
    size_bytes: u64,
    signatures: &[BenchSignature],
    chunk_size_mb: usize,
    chunk_size: usize,
    batch_size: usize,
    progress_interval_ms: u64,
) -> Result<JsonlBenchResult, Box<dyn std::error::Error>> {
    let specs = signature_specs(signatures);
    let matcher = PrefixMatcher::from_specs(&specs)?;
    let overlap_size = matcher.overlap_size();
    let progress_interval = Duration::from_millis(progress_interval_ms);
    let file = File::open(image)?;
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut scan_buf = Vec::<u8>::with_capacity(chunk_size + overlap_size);
    let mut sink = io::sink();
    let started = Instant::now();
    let mut last_progress = started;
    let mut candidates = 0u64;
    let mut events = 0u64;
    let mut bytes_read = 0u64;
    let mut batch_items = Vec::with_capacity(batch_size);

    loop {
        let read_len = reader.read(&mut chunk)?;
        if read_len == 0 {
            break;
        }

        let overlap_len = overlap.len();
        let data_offset = bytes_read.saturating_sub(overlap_len as u64);
        scan_buf.clear();
        scan_buf.extend_from_slice(&overlap);
        scan_buf.extend_from_slice(&chunk[..read_len]);

        for found in matcher.find_iter(&scan_buf) {
            if found.start < overlap_len && found.end <= overlap_len {
                continue;
            }
            let absolute_offset = data_offset + found.start as u64;
            batch_items.push(matcher.candidate_for_pattern(found.pattern_id, absolute_offset));
            candidates += 1;
            if batch_items.len() >= batch_size {
                write_batch_to_sink(&mut sink, &mut batch_items)?;
                events += 1;
            }
        }

        if last_progress.elapsed() >= progress_interval {
            if !batch_items.is_empty() {
                write_batch_to_sink(&mut sink, &mut batch_items)?;
                events += 1;
            }
            write_progress_to_sink(&mut sink)?;
            events += 1;
            last_progress = Instant::now();
        }

        if overlap_size > 0 {
            let keep = overlap_size.min(scan_buf.len());
            overlap.clear();
            overlap.extend_from_slice(&scan_buf[scan_buf.len() - keep..]);
        }
        bytes_read += read_len as u64;
    }

    if !batch_items.is_empty() {
        write_batch_to_sink(&mut sink, &mut batch_items)?;
        events += 1;
    }
    write_progress_to_sink(&mut sink)?;
    write_finished_to_sink(&mut sink)?;
    events += 2;

    let duration = started.elapsed();
    Ok(JsonlBenchResult {
        chunk_size_mb,
        candidate_batch_size: batch_size,
        progress_interval_ms,
        duration_ms: duration.as_millis(),
        mbps: mbps(size_bytes, duration),
        candidates,
        events,
    })
}

fn write_batch_to_sink(
    sink: &mut io::Sink,
    batch_items: &mut Vec<lumina_scan::protocol::CandidateItem>,
) -> io::Result<()> {
    serde_json::to_writer(&mut *sink, batch_items)?;
    sink.write_all(b"\n")?;
    batch_items.clear();
    Ok(())
}

fn write_progress_to_sink(sink: &mut io::Sink) -> io::Result<()> {
    sink.write_all(br#"{"event":"progress"}"#)?;
    sink.write_all(b"\n")?;
    Ok(())
}

fn write_finished_to_sink(sink: &mut io::Sink) -> io::Result<()> {
    sink.write_all(br#"{"event":"finished"}"#)?;
    sink.write_all(b"\n")?;
    sink.flush()?;
    Ok(())
}

fn count_boundary_crossing(
    matcher: &AhoCorasick,
    data: &[u8],
    overlap_len: usize,
    mode: MatcherMode,
) -> u64 {
    match mode {
        MatcherMode::Overlapping => matcher
            .find_overlapping_iter(data)
            .filter(|mat| mat.start() < overlap_len && mat.end() > overlap_len)
            .count() as u64,
        MatcherMode::LeftmostFirst => matcher
            .find_iter(data)
            .filter(|mat| mat.start() < overlap_len && mat.end() > overlap_len)
            .count() as u64,
    }
}

fn count_matches(matcher: &AhoCorasick, data: &[u8], mode: MatcherMode) -> u64 {
    match mode {
        MatcherMode::Overlapping => matcher.find_overlapping_iter(data).count() as u64,
        MatcherMode::LeftmostFirst => matcher.find_iter(data).count() as u64,
    }
}

fn build_aho(
    patterns: &[&[u8]],
    mode: MatcherMode,
) -> Result<AhoCorasick, Box<dyn std::error::Error>> {
    Ok(match mode {
        MatcherMode::Overlapping => AhoCorasick::new(patterns)?,
        MatcherMode::LeftmostFirst => AhoCorasickBuilder::new()
            .match_kind(MatchKind::LeftmostFirst)
            .build(patterns)?,
    })
}

fn collect_matches(
    matcher: &AhoCorasick,
    data: &[u8],
    mode: MatcherMode,
    overlap_len: Option<usize>,
    data_offset: u64,
) -> Vec<FoundCandidate> {
    let mut matches = Vec::new();
    match mode {
        MatcherMode::Overlapping => {
            for mat in matcher.find_overlapping_iter(data) {
                if overlap_len.is_some_and(|len| mat.start() < len && mat.end() <= len) {
                    continue;
                }
                matches.push(FoundCandidate {
                    absolute_offset: data_offset + mat.start() as u64,
                    pattern_id: mat.pattern().as_usize(),
                    buffer_start: mat.start(),
                    buffer_end: mat.end(),
                });
            }
        }
        MatcherMode::LeftmostFirst => {
            for mat in matcher.find_iter(data) {
                if overlap_len.is_some_and(|len| mat.start() < len && mat.end() <= len) {
                    continue;
                }
                matches.push(FoundCandidate {
                    absolute_offset: data_offset + mat.start() as u64,
                    pattern_id: mat.pattern().as_usize(),
                    buffer_start: mat.start(),
                    buffer_end: mat.end(),
                });
            }
        }
    }
    matches
}

fn collect_boundary_matches(
    matcher: &AhoCorasick,
    data: &[u8],
    mode: MatcherMode,
    overlap_len: usize,
    data_offset: u64,
) -> Vec<FoundCandidate> {
    collect_matches(matcher, data, mode, None, data_offset)
        .into_iter()
        .filter(|found| found.buffer_start < overlap_len && found.buffer_end > overlap_len)
        .collect()
}

fn consume_profile_matches(
    matches: Vec<FoundCandidate>,
    signatures: &[&BenchSignature],
    jsonl_enabled: bool,
    counters: &mut ProfileCounters,
    sink: &mut io::Sink,
    batch: &mut Vec<CandidateItem>,
    batch_index: &mut u64,
) -> io::Result<()> {
    counters.candidates += matches.len() as u64;
    if !jsonl_enabled {
        return Ok(());
    }

    for found in matches {
        let batching_started = Instant::now();
        let signature = signatures[found.pattern_id];
        batch.push(CandidateItem {
            offset: found.absolute_offset,
            signature_id: signature.signature_id.to_string(),
            ext: signature.ext.to_string(),
        });
        counters.batching_ns += duration_ns(batching_started.elapsed());

        if batch.len() >= PROFILE_BATCH_SIZE {
            let jsonl_started = Instant::now();
            if flush_profile_batch(sink, batch, batch_index)? {
                counters.events += 1;
            }
            counters.jsonl_ns += duration_ns(jsonl_started.elapsed());
        }
    }

    Ok(())
}

fn flush_profile_batch(
    sink: &mut io::Sink,
    batch: &mut Vec<CandidateItem>,
    batch_index: &mut u64,
) -> io::Result<bool> {
    if batch.is_empty() {
        return Ok(false);
    }
    let event = ScanEvent::Candidates(CandidatesEvent {
        request_id: "profile-breakdown".to_string(),
        batch_index: *batch_index,
        items: batch.clone(),
    });
    serde_json::to_writer(&mut *sink, &event)?;
    sink.write_all(b"\n")?;
    batch.clear();
    *batch_index += 1;
    Ok(true)
}

fn write_profile_progress(
    sink: &mut io::Sink,
    bytes_scanned: u64,
    total_bytes: u64,
    duration: Duration,
) -> io::Result<()> {
    let percent = if total_bytes == 0 {
        100
    } else {
        ((bytes_scanned.saturating_mul(100) / total_bytes).min(100)) as u8
    };
    let event = ScanEvent::Progress(ProgressEvent {
        request_id: "profile-breakdown".to_string(),
        bytes_scanned,
        total_bytes,
        percent,
        mbps: mbps(bytes_scanned, duration),
    });
    serde_json::to_writer(&mut *sink, &event)?;
    sink.write_all(b"\n")?;
    Ok(())
}

fn write_profile_finished(
    sink: &mut io::Sink,
    bytes_scanned: u64,
    candidates: u64,
    duration: Duration,
    size_bytes: u64,
) -> io::Result<()> {
    let event = ScanEvent::Finished(FinishedEvent {
        request_id: "profile-breakdown".to_string(),
        bytes_scanned,
        candidates,
        duration_ms: duration.as_millis(),
        mbps: mbps(size_bytes, duration),
        stopped: false,
    });
    serde_json::to_writer(&mut *sink, &event)?;
    sink.write_all(b"\n")?;
    sink.flush()?;
    Ok(())
}

fn profile_timing_report(duration: Duration, counters: &ProfileCounters) -> ProfileTimingReport {
    let total_ns = duration_ns(duration);
    let accounted = counters.read_ns
        + counters.buffer_ns
        + counters.matching_ns
        + counters.batching_ns
        + counters.jsonl_ns;
    let unaccounted_ns = total_ns.saturating_sub(accounted);

    ProfileTimingReport {
        read: timing_bucket(counters.read_ns, total_ns),
        buffer_overlap: timing_bucket(counters.buffer_ns, total_ns),
        matching: timing_bucket(counters.matching_ns, total_ns),
        batching: timing_bucket(counters.batching_ns, total_ns),
        jsonl_stdout: timing_bucket(counters.jsonl_ns, total_ns),
        unaccounted: timing_bucket(unaccounted_ns, total_ns),
    }
}

fn timing_bucket(ns: u128, total_ns: u128) -> ProfileTimingBucket {
    ProfileTimingBucket {
        ns,
        ms: ns as f64 / 1_000_000.0,
        percent: if total_ns == 0 {
            0.0
        } else {
            (ns as f64 / total_ns as f64) * 100.0
        },
    }
}

fn duration_ns(duration: Duration) -> u128 {
    duration.as_nanos()
}

fn scan_jsonl(
    image: &PathBuf,
    size_bytes: u64,
    signatures: &[BenchSignature],
    chunk_size_mb: usize,
    chunk_size: usize,
    batch_size: usize,
    progress_interval_ms: u64,
) -> Result<JsonlBenchResult, Box<dyn std::error::Error>> {
    let command = ScanCommand {
        request_id: "internal-bench".to_string(),
        source: SourceSpec {
            kind: "image".to_string(),
            path: image.to_string_lossy().to_string(),
            size_bytes: Some(size_bytes),
        },
        signatures: signatures
            .iter()
            .map(|sig| SignatureSpec {
                signature_id: sig.signature_id.to_string(),
                ext: sig.ext.to_string(),
                header_hex: hex(sig.header),
            })
            .collect(),
        chunk_size: Some(chunk_size),
        candidate_batch_size: Some(batch_size),
        progress_interval_ms: Some(progress_interval_ms),
    };

    let started = Instant::now();
    let mut events = 0u64;
    let mut sink = io::sink();
    let summary = scan_image(command, StopControl::new(), |event| {
        events += 1;
        serde_json::to_writer(&mut sink, &event)
            .map_err(|err| lumina_scan::errors::ScanError::Emit(err.to_string()))?;
        sink.write_all(b"\n")
            .map_err(|err| lumina_scan::errors::ScanError::Emit(err.to_string()))?;
        if matches!(event, ScanEvent::Finished(_)) {
            sink.flush()
                .map_err(|err| lumina_scan::errors::ScanError::Emit(err.to_string()))?;
        }
        Ok(())
    })?;
    let duration = started.elapsed();

    Ok(JsonlBenchResult {
        chunk_size_mb,
        candidate_batch_size: batch_size,
        progress_interval_ms,
        duration_ms: duration.as_millis(),
        mbps: mbps(size_bytes, duration),
        candidates: summary.candidates,
        events,
    })
}

fn signature_specs(signatures: &[BenchSignature]) -> Vec<SignatureSpec> {
    signatures
        .iter()
        .map(|sig| SignatureSpec {
            signature_id: sig.signature_id.to_string(),
            ext: sig.ext.to_string(),
            header_hex: hex(sig.header),
        })
        .collect()
}

fn result(
    chunk_size_mb: usize,
    duration: Duration,
    size_bytes: u64,
    bytes_read: u64,
) -> BenchResult {
    BenchResult {
        chunk_size_mb,
        duration_ms: duration.as_millis(),
        mbps: mbps(bytes_read.min(size_bytes), duration),
        candidates: 0,
    }
}

fn result_with_candidates(
    chunk_size_mb: usize,
    duration: Duration,
    size_bytes: u64,
    candidates: u64,
) -> BenchResult {
    BenchResult {
        chunk_size_mb,
        duration_ms: duration.as_millis(),
        mbps: mbps(size_bytes, duration),
        candidates,
    }
}

fn mbps(size_bytes: u64, duration: Duration) -> f64 {
    let secs = duration.as_secs_f64();
    if secs <= 0.0 {
        return 0.0;
    }
    (size_bytes as f64 / (1024.0 * 1024.0)) / secs
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}
