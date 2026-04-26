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

    let signatures = CompiledSignatures::from_specs(&command.signatures, MAX_OVERLAP_SIZE)?;
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

        let overlap_len = overlap.len();
        let data_offset = bytes_scanned.saturating_sub(overlap_len as u64);
        let mut scan_buf = Vec::with_capacity(overlap_len + read_len);
        scan_buf.extend_from_slice(&overlap);
        scan_buf.extend_from_slice(&chunk[..read_len]);

        for mat in signatures.matcher().find_overlapping_iter(&scan_buf) {
            if control.should_stop() {
                stopped = true;
                break;
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
            batch.push(item, &mut emit)?;
            candidate_count += 1;
        }

        bytes_scanned += read_len as u64;

        if overlap_size > 0 {
            let keep = overlap_size.min(scan_buf.len());
            overlap.clear();
            overlap.extend_from_slice(&scan_buf[scan_buf.len() - keep..]);
        }

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

    fn candidate_items(events: &[ScanEvent]) -> Vec<CandidateItem> {
        let mut out = Vec::new();
        for event in events {
            if let ScanEvent::Candidates(batch) = event {
                out.extend(batch.items.clone());
            }
        }
        out
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
}
