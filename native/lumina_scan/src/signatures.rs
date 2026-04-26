use aho_corasick::AhoCorasick;

use crate::{
    errors::ScanError,
    protocol::{CandidateItem, SignatureSpec},
};

#[derive(Debug, Clone)]
pub struct CompiledSignatures {
    matcher: AhoCorasick,
    metadata: Vec<SignatureMeta>,
    max_len: usize,
}

#[derive(Debug, Clone)]
struct SignatureMeta {
    signature_id: String,
    ext: String,
    len: usize,
}

impl CompiledSignatures {
    pub fn from_specs(specs: &[SignatureSpec], overlap_cap: usize) -> Result<Self, ScanError> {
        if specs.is_empty() {
            return Err(ScanError::EmptySignatures);
        }

        let mut patterns = Vec::with_capacity(specs.len());
        let mut metadata = Vec::with_capacity(specs.len());
        let mut max_len = 0usize;

        for spec in specs {
            let bytes =
                decode_hex(&spec.header_hex).map_err(|reason| ScanError::InvalidSignatureHex {
                    signature_id: spec.signature_id.clone(),
                    reason,
                })?;
            if bytes.is_empty() {
                return Err(ScanError::EmptySignature {
                    signature_id: spec.signature_id.clone(),
                });
            }
            max_len = max_len.max(bytes.len());
            metadata.push(SignatureMeta {
                signature_id: spec.signature_id.clone(),
                ext: spec.ext.clone(),
                len: bytes.len(),
            });
            patterns.push(bytes);
        }

        if max_len > overlap_cap + 1 {
            return Err(ScanError::SignatureTooLong {
                max_len,
                cap: overlap_cap,
            });
        }

        let matcher =
            AhoCorasick::new(patterns).map_err(|err| ScanError::MatcherBuild(err.to_string()))?;

        Ok(Self {
            matcher,
            metadata,
            max_len,
        })
    }

    pub fn matcher(&self) -> &AhoCorasick {
        &self.matcher
    }

    pub fn overlap_size(&self) -> usize {
        self.max_len.saturating_sub(1)
    }

    pub fn candidate_for_pattern(&self, pattern_id: usize, offset: u64) -> CandidateItem {
        let meta = &self.metadata[pattern_id];
        CandidateItem {
            offset,
            signature_id: meta.signature_id.clone(),
            ext: meta.ext.clone(),
        }
    }

    pub fn pattern_len(&self, pattern_id: usize) -> usize {
        self.metadata[pattern_id].len
    }
}

pub fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    let compact: String = value.chars().filter(|c| !c.is_whitespace()).collect();
    if compact.len() % 2 != 0 {
        return Err("odd number of hex characters".to_string());
    }

    let mut out = Vec::with_capacity(compact.len() / 2);
    let bytes = compact.as_bytes();
    for pair in bytes.chunks_exact(2) {
        let hi = hex_nibble(pair[0])?;
        let lo = hex_nibble(pair[1])?;
        out.push((hi << 4) | lo);
    }
    Ok(out)
}

fn hex_nibble(byte: u8) -> Result<u8, String> {
    match byte {
        b'0'..=b'9' => Ok(byte - b'0'),
        b'a'..=b'f' => Ok(byte - b'a' + 10),
        b'A'..=b'F' => Ok(byte - b'A' + 10),
        _ => Err(format!("invalid hex byte '{}'", byte as char)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_hex_accepts_whitespace_and_case() {
        assert_eq!(decode_hex("89 50 4e 47").unwrap(), b"\x89PNG");
    }

    #[test]
    fn decode_hex_rejects_odd_length() {
        assert!(decode_hex("abc").is_err());
    }

    #[test]
    fn overlap_is_max_signature_len_minus_one() {
        let specs = vec![
            SignatureSpec {
                signature_id: "a".to_string(),
                ext: ".a".to_string(),
                header_hex: "aa".to_string(),
            },
            SignatureSpec {
                signature_id: "b".to_string(),
                ext: ".b".to_string(),
                header_hex: "01020304".to_string(),
            },
        ];
        let compiled = CompiledSignatures::from_specs(&specs, 4096).unwrap();
        assert_eq!(compiled.overlap_size(), 3);
    }
}
