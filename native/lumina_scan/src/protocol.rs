use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum InputCommand {
    Scan(ScanCommand),
    Stop(StopCommand),
}

#[derive(Debug, Clone, Deserialize)]
pub struct ScanCommand {
    pub request_id: String,
    pub source: SourceSpec,
    pub signatures: Vec<SignatureSpec>,
    pub chunk_size: Option<usize>,
    pub candidate_batch_size: Option<usize>,
    pub progress_interval_ms: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StopCommand {
    pub request_id: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SourceSpec {
    pub kind: String,
    pub path: String,
    pub size_bytes: Option<u64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SignatureSpec {
    pub signature_id: String,
    pub ext: String,
    pub header_hex: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum ScanEvent {
    Progress(ProgressEvent),
    Candidates(CandidatesEvent),
    Finished(FinishedEvent),
    Error(ErrorEvent),
}

#[derive(Debug, Clone, Serialize)]
pub struct ProgressEvent {
    pub request_id: String,
    pub bytes_scanned: u64,
    pub total_bytes: u64,
    pub percent: u8,
    pub mbps: f64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CandidatesEvent {
    pub request_id: String,
    pub batch_index: u64,
    pub items: Vec<CandidateItem>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CandidateItem {
    pub offset: u64,
    pub signature_id: String,
    pub ext: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct FinishedEvent {
    pub request_id: String,
    pub bytes_scanned: u64,
    pub candidates: u64,
    pub duration_ms: u128,
    pub mbps: f64,
    pub stopped: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ErrorEvent {
    pub request_id: String,
    pub code: String,
    pub message: String,
}
