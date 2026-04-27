use std::collections::HashMap;

use crate::{
    errors::ScanError,
    protocol::{CandidateItem, SignatureSpec},
    signatures::decode_hex,
};

#[derive(Debug, Clone)]
pub struct PrefixMatcher {
    signatures: Vec<PrefixSignature>,
    first_bytes: [bool; 256],
    by_u32: HashMap<u32, Vec<usize>>,
    by_u16: HashMap<u16, Vec<usize>>,
    by_u8: [Vec<usize>; 256],
    max_len: usize,
}

#[derive(Debug, Clone)]
struct PrefixSignature {
    signature_id: String,
    ext: String,
    header: Vec<u8>,
    order: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PrefixMatch {
    pub start: usize,
    pub end: usize,
    pub pattern_id: usize,
}

impl PrefixMatcher {
    pub fn from_specs(specs: &[SignatureSpec]) -> Result<Self, ScanError> {
        if specs.is_empty() {
            return Err(ScanError::EmptySignatures);
        }

        let mut signatures = Vec::with_capacity(specs.len());
        for (order, spec) in specs.iter().enumerate() {
            let header =
                decode_hex(&spec.header_hex).map_err(|reason| ScanError::InvalidSignatureHex {
                    signature_id: spec.signature_id.clone(),
                    reason,
                })?;
            if header.is_empty() {
                return Err(ScanError::EmptySignature {
                    signature_id: spec.signature_id.clone(),
                });
            }
            signatures.push(PrefixSignature {
                signature_id: spec.signature_id.clone(),
                ext: spec.ext.clone(),
                header,
                order,
            });
        }

        let max_len = signatures
            .iter()
            .map(|signature| signature.header.len())
            .max()
            .unwrap_or(0);
        let mut matcher = Self {
            signatures,
            first_bytes: [false; 256],
            by_u32: HashMap::new(),
            by_u16: HashMap::new(),
            by_u8: std::array::from_fn(|_| Vec::new()),
            max_len,
        };
        matcher.build_indexes();
        Ok(matcher)
    }

    pub fn max_len(&self) -> usize {
        self.max_len
    }

    pub fn overlap_size(&self) -> usize {
        self.max_len.saturating_sub(1)
    }

    pub fn find_iter<'a>(&'a self, data: &'a [u8]) -> PrefixFindIter<'a> {
        PrefixFindIter {
            matcher: self,
            data,
            pos: 0,
        }
    }

    pub fn find_at(&self, data: &[u8], pos: usize) -> Option<PrefixMatch> {
        let first = *data.get(pos)?;
        if !self.first_bytes[first as usize] {
            return None;
        }

        if pos + 4 <= data.len() {
            let key = u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]);
            if let Some(found) = self.find_in_bucket(self.by_u32.get(&key), data, pos) {
                return Some(found);
            }
        }

        if pos + 2 <= data.len() {
            let key = u16::from_be_bytes([data[pos], data[pos + 1]]);
            if let Some(found) = self.find_in_bucket(self.by_u16.get(&key), data, pos) {
                return Some(found);
            }
        }

        self.find_in_bucket(Some(&self.by_u8[first as usize]), data, pos)
    }

    pub fn candidate_for_pattern(&self, pattern_id: usize, offset: u64) -> CandidateItem {
        let signature = &self.signatures[pattern_id];
        CandidateItem {
            offset,
            signature_id: signature.signature_id.clone(),
            ext: signature.ext.clone(),
        }
    }

    fn build_indexes(&mut self) {
        for (idx, signature) in self.signatures.iter().enumerate() {
            let first = signature.header[0];
            self.first_bytes[first as usize] = true;
            if signature.header.len() >= 4 {
                let key = u32::from_be_bytes([
                    signature.header[0],
                    signature.header[1],
                    signature.header[2],
                    signature.header[3],
                ]);
                self.by_u32.entry(key).or_default().push(idx);
            } else if signature.header.len() >= 2 {
                let key = u16::from_be_bytes([signature.header[0], signature.header[1]]);
                self.by_u16.entry(key).or_default().push(idx);
            } else {
                self.by_u8[first as usize].push(idx);
            }
        }

        let signatures = &self.signatures;
        for bucket in self.by_u32.values_mut() {
            sort_bucket(signatures, bucket);
        }
        for bucket in self.by_u16.values_mut() {
            sort_bucket(signatures, bucket);
        }
        for bucket in self.by_u8.iter_mut() {
            sort_bucket(signatures, bucket);
        }
    }

    fn find_in_bucket(
        &self,
        bucket: Option<&Vec<usize>>,
        data: &[u8],
        pos: usize,
    ) -> Option<PrefixMatch> {
        for &pattern_id in bucket? {
            let signature = &self.signatures[pattern_id];
            let end = pos + signature.header.len();
            if end <= data.len() && data[pos..end] == signature.header {
                return Some(PrefixMatch {
                    start: pos,
                    end,
                    pattern_id,
                });
            }
        }
        None
    }
}

fn sort_bucket(signatures: &[PrefixSignature], bucket: &mut [usize]) {
    bucket.sort_by_key(|&idx| {
        (
            std::cmp::Reverse(signatures[idx].header.len()),
            signatures[idx].order,
        )
    });
}

pub struct PrefixFindIter<'a> {
    matcher: &'a PrefixMatcher,
    data: &'a [u8],
    pos: usize,
}

impl Iterator for PrefixFindIter<'_> {
    type Item = PrefixMatch;

    fn next(&mut self) -> Option<Self::Item> {
        while self.pos < self.data.len() {
            let pos = self.pos;
            if let Some(found) = self.matcher.find_at(self.data, pos) {
                self.pos = found.end;
                return Some(found);
            }
            self.pos += 1;
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(id: &str, ext: &str, bytes: &[u8]) -> SignatureSpec {
        SignatureSpec {
            signature_id: id.to_string(),
            ext: ext.to_string(),
            header_hex: hex(bytes),
        }
    }

    fn hex(bytes: &[u8]) -> String {
        let mut out = String::new();
        for byte in bytes {
            out.push_str(&format!("{byte:02x}"));
        }
        out
    }

    fn matches(matcher: &PrefixMatcher, data: &[u8]) -> Vec<(usize, usize, String)> {
        matcher
            .find_iter(data)
            .map(|m| {
                (
                    m.start,
                    m.end,
                    matcher.signatures[m.pattern_id].signature_id.clone(),
                )
            })
            .collect()
    }

    #[test]
    fn leftmost_longest_prefers_longest_prefix_signature() {
        let matcher = PrefixMatcher::from_specs(&[
            spec("abc", ".a", b"ABC"),
            spec("abcd", ".a", b"ABCD"),
            spec("abcde", ".a", b"ABCDE"),
        ])
        .unwrap();

        assert_eq!(
            matches(&matcher, b"xxABCDEyy"),
            vec![(2, 7, "abcde".to_string())]
        );
    }

    #[test]
    fn adjacent_matches_are_emitted() {
        let matcher =
            PrefixMatcher::from_specs(&[spec("png", ".png", b"PNG"), spec("pdf", ".pdf", b"PDF")])
                .unwrap();

        assert_eq!(
            matches(&matcher, b"PNGPDF"),
            vec![(0, 3, "png".to_string()), (3, 6, "pdf".to_string())]
        );
    }

    #[test]
    fn multiple_matches_in_buffer_are_emitted_left_to_right() {
        let matcher = PrefixMatcher::from_specs(&[
            spec("zip", ".zip", b"PK\x03\x04"),
            spec("gif", ".gif", b"GIF87a"),
        ])
        .unwrap();

        assert_eq!(
            matches(&matcher, b"aaPK\x03\x04bbGIF87acc"),
            vec![(2, 6, "zip".to_string()), (8, 14, "gif".to_string())]
        );
    }

    #[test]
    fn split_boundary_match_can_be_found_in_joined_overlap_window() {
        let matcher =
            PrefixMatcher::from_specs(&[spec("png", ".png", b"\x89PNG\r\n\x1a\n")]).unwrap();
        let previous_tail = b"abc\x89PN";
        let current_prefix = b"G\r\n\x1a\nxyz";
        let mut boundary = Vec::new();
        boundary.extend_from_slice(previous_tail);
        boundary.extend_from_slice(current_prefix);
        let overlap_len = previous_tail.len();

        let crossing: Vec<_> = matcher
            .find_iter(&boundary)
            .filter(|m| m.start < overlap_len && m.end > overlap_len)
            .collect();

        assert_eq!(crossing.len(), 1);
        assert_eq!(crossing[0].start, 3);
    }

    #[test]
    fn ambiguous_same_length_prefix_uses_input_order() {
        let matcher = PrefixMatcher::from_specs(&[
            spec("first", ".a", b"ABCD"),
            spec("second", ".b", b"ABCD"),
        ])
        .unwrap();

        assert_eq!(
            matches(&matcher, b"ABCD"),
            vec![(0, 4, "first".to_string())]
        );
    }
}
