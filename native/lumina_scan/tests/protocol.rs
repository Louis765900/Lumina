use lumina_scan::protocol::{CandidateItem, InputCommand, ScanEvent};

#[test]
fn parses_scan_command_jsonl() {
    let raw = r#"{
        "cmd": "scan",
        "request_id": "b1-001",
        "source": {
            "kind": "image",
            "path": "C:\\cases\\sample.img",
            "size_bytes": 1024
        },
        "signatures": [
            {
                "signature_id": "png_89504e47",
                "ext": ".png",
                "header_hex": "89504e470d0a1a0a"
            }
        ],
        "chunk_size": 8388608,
        "candidate_batch_size": 512,
        "progress_interval_ms": 250
    }"#;

    let command: InputCommand = serde_json::from_str(raw).unwrap();
    match command {
        InputCommand::Scan(scan) => {
            assert_eq!(scan.request_id, "b1-001");
            assert_eq!(scan.source.kind, "image");
            assert_eq!(scan.signatures[0].signature_id, "png_89504e47");
            assert_eq!(scan.candidate_batch_size, Some(512));
        }
        InputCommand::Stop(_) => panic!("expected scan command"),
    }
}

#[test]
fn parses_stop_command_jsonl() {
    let command: InputCommand =
        serde_json::from_str(r#"{"cmd":"stop","request_id":"b1-001"}"#).unwrap();

    match command {
        InputCommand::Stop(stop) => assert_eq!(stop.request_id, "b1-001"),
        InputCommand::Scan(_) => panic!("expected stop command"),
    }
}

#[test]
fn serializes_candidates_batch_event() {
    let event = ScanEvent::Candidates(lumina_scan::protocol::CandidatesEvent {
        request_id: "b1-001".to_string(),
        batch_index: 3,
        items: vec![CandidateItem {
            offset: 123,
            signature_id: "pdf_25504446".to_string(),
            ext: ".pdf".to_string(),
        }],
    });

    let json = serde_json::to_string(&event).unwrap();
    assert!(json.contains(r#""event":"candidates""#));
    assert!(json.contains(r#""batch_index":3"#));
    assert!(json.contains(r#""offset":123"#));
}
