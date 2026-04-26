use thiserror::Error;

#[derive(Debug, Error)]
pub enum ScanError {
    #[error("unsupported source kind: {0}")]
    UnsupportedSource(String),

    #[error("no signatures provided")]
    EmptySignatures,

    #[error("signature {signature_id} has invalid hex: {reason}")]
    InvalidSignatureHex {
        signature_id: String,
        reason: String,
    },

    #[error("signature {signature_id} is empty")]
    EmptySignature { signature_id: String },

    #[error("maximum signature length {max_len} exceeds overlap cap {cap}")]
    SignatureTooLong { max_len: usize, cap: usize },

    #[error("failed to build matcher: {0}")]
    MatcherBuild(String),

    #[error("cannot open image {path}: {source}")]
    OpenImage {
        path: String,
        source: std::io::Error,
    },

    #[error("read failed at offset {offset}: {source}")]
    Read { offset: u64, source: std::io::Error },

    #[error("event emission failed: {0}")]
    Emit(String),
}
