use std::{
    fs::File,
    io::{BufReader, Read},
    time::{Duration, Instant},
};

use crate::{
    control::StopControl,
    errors::ScanError,
    protocol::{
        CandidateItem, CandidatesEvent, FinishedEvent, ProgressEvent, ScanCommand, ScanEvent,
    },
    signatures::CompiledSignatures,
};

pub const DEFAULT_CHUNK_SIZE: usize = 16 * 1024 * 1024;
pub const DEFAULT_BATCH_SIZE: usize = 512;
pub const DEFAULT_PROGRESS_INTERVAL_MS: u64 = 250;
pub const MAX_OVERLAP_SIZE: usize = 4096;
pub const MATCHER_MODE_ENV: &str = "LUMINA_NATIVE_MATCHER";

#[derive(Debug, Clone, PartialEq)]
pub struct ScanSummary {
    pub bytes_scanned: u64,
    pub candidates: u64,
    pub duration_ms: u128,
    pub mbps: f64,
    pub stopped: bool,
}

#[derive(Debug)]
struct CandidateBatch {
    request_id: String,
    batch_index: u64,
    batch_size: usize,
    items: Vec<CandidateItem>,
}

impl CandidateBatch {
    fn new(request_id: String, batch_size: usize) -> Self {
        Self {
            request_id,
            batch_index: 0,
            batch_size: batch_size.max(1),
            items: Vec::with_capacity(batch_size.max(1)),
        }
    }

    fn push<F>(&mut self, item: CandidateItem, emit: &mut F) -> Result<(), ScanError>
    where
        F: FnMut(ScanEvent) -> Result<(), ScanError>,
    {
        self.items.push(item);
        if self.items.len() >= self.batch_size {
            self.flush(emit)?;
        }
        Ok(())
    }

    fn flush<F>(&mut self, emit: &mut F) -> Result<(), ScanError>
    where
        F: FnMut(ScanEvent) -> Result<(), ScanError>,
    {
        if self.items.is_empty() {
            return Ok(());
        }

        let items = std::mem::take(&mut self.items);
        emit(ScanEvent::Candidates(CandidatesEvent {
            request_id: self.request_id.clone(),
            batch_index: self.batch_index,
            items,
        }))?;
        self.batch_index += 1;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ScannerMode {
    OverlappingCopy,
    LeftmostNoCopy,
}

impl ScannerMode {
    fn from_env() -> Self {
        match std::env::var(MATCHER_MODE_ENV) {
            Ok(value) if value.eq_ignore_ascii_case("leftmost_no_copy") => Self::LeftmostNoCopy,
            Ok(value) if value.eq_ignore_ascii_case("overlapping_copy") => Self::OverlappingCopy,
            _ => Self::LeftmostNoCopy,
        }
    }
}

pub fn scan_image<F>(
    command: ScanCommand,
    control: StopControl,
    mut emit: F,
) -> Result<ScanSummary, ScanError>
where
    F: FnMut(ScanEvent) -> Result<(), ScanError>,
{
    if command.source.kind != "image" {
        return Err(ScanError::UnsupportedSource(command.source.kind));
    }

    let scanner_mode = ScannerMode::from_env();
    let signatures = match scanner_mode {
        ScannerMode::OverlappingCopy => {
            CompiledSignatures::from_specs(&command.signatures, MAX_OVERLAP_SIZE)?
        }
        ScannerMode::LeftmostNoCopy => {
            CompiledSignatures::from_specs_leftmost_first(&command.signatures, MAX_OVERLAP_SIZE)?
        }
    };
    let overlap_size = signatures.overlap_size();
    let chunk_size = command
        .chunk_size
        .unwrap_or(DEFAULT_CHUNK_SIZE)
        .max(64 * 1024);
    let batch_size = command
        .candidate_batch_size
        .unwrap_or(DEFAULT_BATCH_SIZE)
        .max(1);
    let progress_interval = Duration::from_millis(
        command
            .progress_interval_ms
            .unwrap_or(DEFAULT_PROGRESS_INTERVAL_MS),
    );

    let file = File::open(&command.source.path).map_err(|source| ScanError::OpenImage {
        path: command.source.path.clone(),
        source,
    })?;
    let total_bytes = command
        .source
        .size_bytes
        .or_else(|| file.metadata().ok().map(|m| m.len()))
        .unwrap_or(0);
    let mut reader = BufReader::with_capacity(chunk_size, file);
    let mut chunk = vec![0u8; chunk_size];
    let mut overlap = Vec::<u8>::with_capacity(overlap_size);
    let mut boundary = Vec::<u8>::with_capacity(overlap_size.saturating_mul(2));
    let mut batch = CandidateBatch::new(command.request_id.clone(), batch_size);

    let started = Instant::now();
    let mut last_progress = started;
    let mut bytes_scanned = 0u64;
    let mut candidate_count = 0u64;
    let mut stopped = false;

    loop {
        if control.should_stop() {
            stopped = true;
            break;
        }

        let read_len = reader.read(&mut chunk).map_err(|source| ScanError::Read {
            offset: bytes_scanned,
            source,
        })?;

        if read_len == 0 {
            break;
        }

        if control.should_stop() {
            stopped = true;
            break;
        }

        match scanner_mode {
            ScannerMode::OverlappingCopy => {
                let scan = scan_overlapping_copy_chunk(
                    &signatures,
                    &mut batch,
                    &mut emit,
                    &control,
                    &overlap,
                    &chunk[..read_len],
                    bytes_scanned,
                )?;
                candidate_count += scan.candidates;
                stopped = scan.stopped;
                if overlap_size > 0 {
                    update_overlap_from_joined(&mut overlap, overlap_size, &chunk[..read_len]);
                }
            }
            ScannerMode::LeftmostNoCopy => {
                let scan = scan_leftmost_no_copy_chunk(
                    &signatures,
                    &mut batch,
                    &mut emit,
                    &control,
                    &overlap,
                    &mut boundary,
                    &chunk[..read_len],
                    bytes_scanned,
                )?;
                candidate_count += scan.candidates;
                stopped = scan.stopped;
                if overlap_size > 0 {
                    update_overlap_from_chunk(&mut overlap, overlap_size, &chunk[..read_len]);
                }
            }
        }

        bytes_scanned += read_len as u64;

        if stopped {
            break;
        }

        if last_progress.elapsed() >= progress_interval {
            batch.flush(&mut emit)?;
            if control.should_stop() {
                stopped = true;
                break;
            }
            emit(progress_event(
                &command.request_id,
                bytes_scanned,
                total_bytes,
                started,
            ))?;
            last_progress = Instant::now();
        }
    }

    batch.flush(&mut emit)?;
    emit(progress_event(
        &command.request_id,
        bytes_scanned,
        total_bytes,
        started,
    ))?;

    let duration = started.elapsed();
    let mbps = mbps(bytes_scanned, duration);
    let summary = ScanSummary {
        bytes_scanned,
        candidates: candidate_count,
        duration_ms: duration.as_millis(),
        mbps,
        stopped,
    };

    emit(ScanEvent::Finished(FinishedEvent {
        request_id: command.request_id,
        bytes_scanned: summary.bytes_scanned,
        candidates: summary.candidates,
        duration_ms: summary.duration_ms,
        mbps: summary.mbps,
        stopped: summary.stopped,
    }))?;

    Ok(summary)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ChunkScan {
    candidates: u64,
    stopped: bool,
}

fn scan_overlapping_copy_chunk<F>(
    signatures: &CompiledSignatures,
    batch: &mut CandidateBatch,
    emit: &mut F,
    control: &StopControl,
    overlap: &[u8],
    chunk: &[u8],
    bytes_scanned: u64,
) -> Result<ChunkScan, ScanError>
where
    F: FnMut(ScanEvent) -> Result<(), ScanError>,
{
    let overlap_len = overlap.len();
    let data_offset = bytes_scanned.saturating_sub(overlap_len as u64);
    let mut scan_buf = Vec::with_capacity(overlap_len + chunk.len());
    scan_buf.extend_from_slice(overlap);
    scan_buf.extend_from_slice(chunk);
    let mut candidates = 0u64;

    for mat in signatures.matcher().find_overlapping_iter(&scan_buf) {
        if control.should_stop() {
            return Ok(ChunkScan {
                candidates,
                stopped: true,
            });
        }

        if mat.start() < overlap_len && mat.end() <= overlap_len {
            continue;
        }

        let pattern_id = mat.pattern().as_usize();
        let expected_end = mat.start() + signatures.pattern_len(pattern_id);
        if expected_end != mat.end() {
            continue;
        }

        let absolute_offset = data_offset + mat.start() as u64;
        let item = signatures.candidate_for_pattern(pattern_id, absolute_offset);
        batch.push(item, emit)?;
        candidates += 1;
    }

    Ok(ChunkScan {
        candidates,
        stopped: false,
    })
}

fn scan_leftmost_no_copy_chunk<F>(
    signatures: &CompiledSignatures,
    batch: &mut CandidateBatch,
    emit: &mut F,
    control: &StopControl,
    overlap: &[u8],
    boundary: &mut Vec<u8>,
    chunk: &[u8],
    bytes_scanned: u64,
) -> Result<ChunkScan, ScanError>
where
    F: FnMut(ScanEvent) -> Result<(), ScanError>,
{
    let mut candidates = 0u64;
    let overlap_len = overlap.len();
    let overlap_size = signatures.overlap_size();

    if overlap_len > 0 {
        let prefix_len = overlap_size.min(chunk.len());
        boundary.clear();
        boundary.extend_from_slice(overlap);
        boundary.extend_from_slice(&chunk[..prefix_len]);
        let data_offset = bytes_scanned.saturating_sub(overlap_len as u64);
        for mat in signatures.matcher().find_iter(boundary.as_slice()) {
            if control.should_stop() {
                return Ok(ChunkScan {
                    candidates,
                    stopped: true,
                });
            }

            if !(mat.start() < overlap_len && mat.end() > overlap_len) {
                continue;
            }

            let pattern_id = mat.pattern().as_usize();
            let expected_end = mat.start() + signatures.pattern_len(pattern_id);
            if expected_end != mat.end() {
                continue;
            }

            let absolute_offset = data_offset + mat.start() as u64;
            let item = signatures.candidate_for_pattern(pattern_id, absolute_offset);
            batch.push(item, emit)?;
            candidates += 1;
        }
    }

    for mat in signatures.matcher().find_iter(chunk) {
        if control.should_stop() {
            return Ok(ChunkScan {
                candidates,
                stopped: true,
            });
        }

        let pattern_id = mat.pattern().as_usize();
        let expected_end = mat.start() + signatures.pattern_len(pattern_id);
        if expected_end != mat.end() {
            continue;
        }

        let absolute_offset = bytes_scanned + mat.start() as u64;
        let item = signatures.candidate_for_pattern(pattern_id, absolute_offset);
        batch.push(item, emit)?;
        candidates += 1;
    }

    Ok(ChunkScan {
        candidates,
        stopped: false,
    })
}

fn update_overlap_from_joined(overlap: &mut Vec<u8>, overlap_size: usize, chunk: &[u8]) {
    if overlap_size == 0 {
        return;
    }

    if chunk.len() >= overlap_size {
        overlap.clear();
        overlap.extend_from_slice(&chunk[chunk.len() - overlap_size..]);
        return;
    }

    let old_overlap = std::mem::take(overlap);
    overlap.extend_from_slice(&old_overlap);
    overlap.extend_from_slice(chunk);
    let keep = overlap_size.min(overlap.len());
    if keep < overlap.len() {
        overlap.drain(..overlap.len() - keep);
    }
}

fn update_overlap_from_chunk(overlap: &mut Vec<u8>, overlap_size: usize, chunk: &[u8]) {
    if overlap_size == 0 {
        return;
    }

    if chunk.len() >= overlap_size {
        overlap.clear();
        overlap.extend_from_slice(&chunk[chunk.len() - overlap_size..]);
        return;
    }

    overlap.extend_from_slice(chunk);
    let keep = overlap_size.min(overlap.len());
    if keep < overlap.len() {
        overlap.drain(..overlap.len() - keep);
    }
}

fn progress_event(
    request_id: &str,
    bytes_scanned: u64,
    total_bytes: u64,
    started: Instant,
) -> ScanEvent {
    let percent = if total_bytes > 0 {
        ((bytes_scanned.saturating_mul(100) / total_bytes).min(100)) as u8
    } else {
        0
    };

    ScanEvent::Progress(ProgressEvent {
        request_id: request_id.to_string(),
        bytes_scanned,
        total_bytes,
        percent,
        mbps: mbps(bytes_scanned, started.elapsed()),
    })
}

fn mbps(bytes_scanned: u64, duration: Duration) -> f64 {
    let secs = duration.as_secs_f64();
    if secs <= 0.0 {
        return 0.0;
    }
    (bytes_scanned as f64 / (1024.0 * 1024.0)) / secs
}

#[cfg(test)]
mod tests {
    use std::{
        fs,
        path::PathBuf,
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc,
        },
        time::{SystemTime, UNIX_EPOCH},
    };

    use super::*;
    use crate::protocol::{SignatureSpec, SourceSpec};

    fn temp_image(bytes: &[u8]) -> PathBuf {
        let mut path = std::env::temp_dir();
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        path.push(format!("lumina_scan_test_{nanos}.img"));
        fs::write(&path, bytes).unwrap();
        path
    }

    fn command(path: &PathBuf, signatures: Vec<SignatureSpec>) -> ScanCommand {
        ScanCommand {
            request_id: "test".to_string(),
            source: SourceSpec {
                kind: "image".to_string(),
                path: path.to_string_lossy().to_string(),
                size_bytes: Some(fs::metadata(path).unwrap().len()),
            },
            signatures,
            chunk_size: Some(4),
            candidate_batch_size: Some(2),
            progress_interval_ms: Some(1_000_000),
        }
    }

    fn sig(id: &str, ext: &str, hex: &str) -> SignatureSpec {
        SignatureSpec {
            signature_id: id.to_string(),
            ext: ext.to_string(),
            header_hex: hex.to_string(),
        }
    }

    fn sig_bytes(id: &str, ext: &str, bytes: &[u8]) -> SignatureSpec {
        sig(id, ext, &hex(bytes))
    }

    fn hex(bytes: &[u8]) -> String {
        let mut out = String::new();
        for byte in bytes {
            out.push_str(&format!("{byte:02x}"));
        }
        out
    }

    fn candidate_items(events: &[ScanEvent]) -> Vec<CandidateItem> {
        let mut out = Vec::new();
        for event in events {
            if let ScanEvent::Candidates(batch) = event {
                out.extend(batch.items.clone());
            }
        }
        out
    }

    fn leftmost_no_copy_items(
        data: &[u8],
        signatures: Vec<SignatureSpec>,
        chunk_size: usize,
    ) -> Vec<CandidateItem> {
        let compiled =
            CompiledSignatures::from_specs_leftmost_first(&signatures, MAX_OVERLAP_SIZE).unwrap();
        let mut batch = CandidateBatch::new("test".to_string(), 1024);
        let mut events = Vec::new();
        let mut overlap = Vec::with_capacity(compiled.overlap_size());
        let mut boundary = Vec::with_capacity(compiled.overlap_size().saturating_mul(2));
        let mut bytes_scanned = 0u64;

        for chunk in data.chunks(chunk_size) {
            scan_leftmost_no_copy_chunk(
                &compiled,
                &mut batch,
                &mut |event| {
                    events.push(event);
                    Ok(())
                },
                &StopControl::new(),
                &overlap,
                &mut boundary,
                chunk,
                bytes_scanned,
            )
            .unwrap();
            update_overlap_from_chunk(&mut overlap, compiled.overlap_size(), chunk);
            bytes_scanned += chunk.len() as u64;
        }

        batch
            .flush(&mut |event| {
                events.push(event);
                Ok(())
            })
            .unwrap();
        candidate_items(&events)
    }

    fn regex_simulated_items(data: &[u8], signatures: &[SignatureSpec]) -> Vec<CandidateItem> {
        let mut decoded: Vec<(usize, &SignatureSpec, Vec<u8>)> = signatures
            .iter()
            .enumerate()
            .map(|(idx, sig)| {
                (
                    idx,
                    sig,
                    crate::signatures::decode_hex(&sig.header_hex).unwrap(),
                )
            })
            .collect();
        decoded.sort_by_key(|(idx, _, bytes)| (std::cmp::Reverse(bytes.len()), *idx));

        let mut items = Vec::new();
        let mut pos = 0usize;
        while pos < data.len() {
            let mut found = None;
            for (_, sig, bytes) in &decoded {
                let end = pos + bytes.len();
                if end <= data.len() && data[pos..end] == *bytes.as_slice() {
                    found = Some((*sig, bytes.len()));
                    break;
                }
            }

            if let Some((sig, len)) = found {
                items.push(CandidateItem {
                    offset: pos as u64,
                    signature_id: sig.signature_id.clone(),
                    ext: sig.ext.clone(),
                });
                pos += len;
            } else {
                pos += 1;
            }
        }
        items
    }

    #[test]
    fn finds_single_signature_in_image() {
        let path = temp_image(b"xxPNGyy");
        let mut events = Vec::new();
        let summary = scan_image(
            command(&path, vec![sig("png", ".png", "504e47")]),
            StopControl::new(),
            |event| {
                events.push(event);
                Ok(())
            },
        )
        .unwrap();

        fs::remove_file(path).ok();
        assert_eq!(summary.candidates, 1);
        assert_eq!(candidate_items(&events)[0].offset, 2);
    }

    #[test]
    fn finds_signature_split_across_chunks() {
        let path = temp_image(b"xxABCDyy");
        let mut events = Vec::new();
        let summary = scan_image(
            command(&path, vec![sig("abcd", ".bin", "41424344")]),
            StopControl::new(),
            |event| {
                events.push(event);
                Ok(())
            },
        )
        .unwrap();

        fs::remove_file(path).ok();
        assert_eq!(summary.candidates, 1);
        assert_eq!(candidate_items(&events)[0].offset, 2);
    }

    #[test]
    fn batches_candidates() {
        let path = temp_image(b"AAxxAAxxAA");
        let mut events = Vec::new();
        let summary = scan_image(
            command(&path, vec![sig("aa", ".a", "4141")]),
            StopControl::new(),
            |event| {
                events.push(event);
                Ok(())
            },
        )
        .unwrap();

        fs::remove_file(path).ok();
        let batch_sizes: Vec<usize> = events
            .iter()
            .filter_map(|event| match event {
                ScanEvent::Candidates(batch) => Some(batch.items.len()),
                _ => None,
            })
            .collect();
        assert_eq!(summary.candidates, 3);
        assert_eq!(batch_sizes, vec![2, 1]);
    }

    #[test]
    fn stop_is_checked_during_match_iteration() {
        let path = temp_image(b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
        let stop_flag = Arc::new(AtomicBool::new(false));
        let mut events = Vec::new();
        let mut cmd = command(&path, vec![sig("aa", ".a", "4141")]);
        cmd.candidate_batch_size = Some(1);
        cmd.chunk_size = Some(64 * 1024);

        let summary = scan_image(cmd, StopControl::from_flag(stop_flag.clone()), |event| {
            if matches!(&event, ScanEvent::Candidates(_)) {
                stop_flag.store(true, Ordering::SeqCst);
            }
            events.push(event);
            Ok(())
        })
        .unwrap();

        fs::remove_file(path).ok();
        assert!(summary.stopped);
        assert!(summary.candidates < 31);
        assert!(matches!(events.last(), Some(ScanEvent::Finished(done)) if done.stopped));
    }

    #[test]
    fn rejects_non_image_sources() {
        let path = temp_image(b"abc");
        let mut cmd = command(&path, vec![sig("a", ".a", "61")]);
        cmd.source.kind = "physical_drive".to_string();
        let err = scan_image(cmd, StopControl::new(), |_| Ok(())).unwrap_err();

        fs::remove_file(path).ok();
        assert!(matches!(err, ScanError::UnsupportedSource(_)));
    }

    #[test]
    fn leftmost_no_copy_prefixes_choose_longest() {
        let signatures = vec![
            sig_bytes("abc", ".a", b"ABC"),
            sig_bytes("abcd", ".a", b"ABCD"),
            sig_bytes("abcde", ".a", b"ABCDE"),
        ];

        let items = leftmost_no_copy_items(b"xxABCDEyy", signatures, 4);

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].offset, 2);
        assert_eq!(items[0].signature_id, "abcde");
    }

    #[test]
    fn leftmost_no_copy_emits_adjacent_matches() {
        let signatures = vec![
            sig_bytes("abc", ".a", b"ABC"),
            sig_bytes("def", ".d", b"DEF"),
        ];

        let items = leftmost_no_copy_items(b"ABCDEF", signatures, 3);
        let offsets: Vec<_> = items.iter().map(|item| item.offset).collect();
        let ids: Vec<_> = items
            .iter()
            .map(|item| item.signature_id.as_str())
            .collect();

        assert_eq!(offsets, vec![0, 3]);
        assert_eq!(ids, vec!["abc", "def"]);
    }

    #[test]
    fn leftmost_no_copy_finds_signature_split_between_chunks() {
        let signatures = vec![sig_bytes("abcd", ".bin", b"ABCD")];

        let items = leftmost_no_copy_items(b"xxABCDyy", signatures, 4);

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].offset, 2);
    }

    #[test]
    fn leftmost_no_copy_does_not_duplicate_near_boundary() {
        let signatures = vec![sig_bytes("abcd", ".bin", b"ABCD")];

        let items = leftmost_no_copy_items(b"xxxABCDzz", signatures, 5);

        assert_eq!(items.len(), 1);
        assert_eq!(items[0].offset, 3);
    }

    #[test]
    fn leftmost_no_copy_absolute_offsets_are_exact() {
        let signatures = vec![
            sig_bytes("png", ".png", b"PNG"),
            sig_bytes("pdf", ".pdf", b"PDF"),
            sig_bytes("zip", ".zip", b"PK\x03\x04"),
        ];

        let items = leftmost_no_copy_items(b"PNGxxPDFxxPK\x03\x04tail", signatures, 5);
        let offsets: Vec<_> = items.iter().map(|item| item.offset).collect();
        let ids: Vec<_> = items
            .iter()
            .map(|item| item.signature_id.as_str())
            .collect();

        assert_eq!(offsets, vec![0, 5, 10]);
        assert_eq!(ids, vec!["png", "pdf", "zip"]);
    }

    #[test]
    fn leftmost_no_copy_matches_simulated_python_regex_semantics() {
        let signatures = vec![
            sig_bytes("abc", ".a", b"ABC"),
            sig_bytes("abcde", ".a", b"ABCDE"),
            sig_bytes("pdf", ".pdf", b"%PDF-"),
            sig_bytes("zip", ".zip", b"PK\x03\x04"),
            sig_bytes("png", ".png", b"\x89PNG\r\n\x1a\n"),
        ];
        let data = b"noiseABCDEABCPK\x03\x04xx%PDF-\x89PNG\r\n\x1a\nABC";

        let expected = regex_simulated_items(data, &signatures);
        let found = leftmost_no_copy_items(data, signatures, 7);

        assert_eq!(found, expected);
    }
}
