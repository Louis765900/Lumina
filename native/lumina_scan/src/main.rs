use std::{
    collections::HashMap,
    io::{self, BufRead, BufWriter, Write},
    sync::{Arc, Mutex},
    thread,
};

use lumina_scan::{
    control::StopControl,
    errors::ScanError,
    protocol::{ErrorEvent, InputCommand, ScanEvent},
    scanner::scan_image,
};

type SharedWriter = Arc<Mutex<BufWriter<io::Stdout>>>;
type ActiveScans = Arc<Mutex<HashMap<String, StopControl>>>;

fn main() {
    let stdout = Arc::new(Mutex::new(BufWriter::new(io::stdout())));
    let active: ActiveScans = Arc::new(Mutex::new(HashMap::new()));
    let stdin = io::stdin();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(line) => line,
            Err(err) => {
                emit_error(&stdout, "", "stdin_read_failed", &err.to_string());
                break;
            }
        };

        if line.trim().is_empty() {
            continue;
        }

        let command: InputCommand = match serde_json::from_str(&line) {
            Ok(command) => command,
            Err(err) => {
                emit_error(&stdout, "", "invalid_json", &err.to_string());
                continue;
            }
        };

        match command {
            InputCommand::Scan(scan) => {
                let request_id = scan.request_id.clone();
                let control = StopControl::new();
                {
                    let mut active_guard = active.lock().expect("active scan mutex poisoned");
                    if active_guard.contains_key(&request_id) {
                        emit_error(
                            &stdout,
                            &request_id,
                            "duplicate_request",
                            "a scan with this request_id is already active",
                        );
                        continue;
                    }
                    active_guard.insert(request_id.clone(), control.clone());
                }

                let writer = stdout.clone();
                let active_scans = active.clone();
                thread::spawn(move || {
                    let result = scan_image(scan, control, |event| write_event(&writer, &event));
                    if let Err(err) = result {
                        emit_error(&writer, &request_id, error_code(&err), &err.to_string());
                    }
                    active_scans
                        .lock()
                        .expect("active scan mutex poisoned")
                        .remove(&request_id);
                });
            }
            InputCommand::Stop(stop) => {
                let maybe_control = active
                    .lock()
                    .expect("active scan mutex poisoned")
                    .get(&stop.request_id)
                    .cloned();

                match maybe_control {
                    Some(control) => control.stop(),
                    None => emit_error(
                        &stdout,
                        &stop.request_id,
                        "unknown_request",
                        "no active scan exists for this request_id",
                    ),
                }
            }
        }
    }
}

fn write_event(writer: &SharedWriter, event: &ScanEvent) -> Result<(), ScanError> {
    let mut guard = writer
        .lock()
        .map_err(|_| ScanError::Emit("stdout mutex poisoned".to_string()))?;
    serde_json::to_writer(&mut *guard, event).map_err(|err| ScanError::Emit(err.to_string()))?;
    guard
        .write_all(b"\n")
        .map_err(|err| ScanError::Emit(err.to_string()))?;
    guard
        .flush()
        .map_err(|err| ScanError::Emit(err.to_string()))?;
    Ok(())
}

fn emit_error(writer: &SharedWriter, request_id: &str, code: &str, message: &str) {
    let event = ScanEvent::Error(ErrorEvent {
        request_id: request_id.to_string(),
        code: code.to_string(),
        message: message.to_string(),
    });
    let _ = write_event(writer, &event);
}

fn error_code(err: &ScanError) -> &'static str {
    match err {
        ScanError::UnsupportedSource(_) => "unsupported_source",
        ScanError::EmptySignatures => "empty_signatures",
        ScanError::InvalidSignatureHex { .. } => "invalid_signature_hex",
        ScanError::EmptySignature { .. } => "empty_signature",
        ScanError::SignatureTooLong { .. } => "signature_too_long",
        ScanError::MatcherBuild(_) => "matcher_build_failed",
        ScanError::OpenImage { .. } => "open_failed",
        ScanError::Read { .. } => "read_failed",
        ScanError::Emit(_) => "emit_failed",
    }
}
