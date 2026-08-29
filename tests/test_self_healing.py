from __future__ import annotations

from anbar.db import Database
from anbar.objects import Manifest
from anbar.self_healing import (
    decode_chunk_caption,
    decode_meta_event,
    encode_chunk_caption,
    encode_meta_event,
    rebuild_from_manifests,
)


def test_encode_decode_unencrypted():
    cap = encode_chunk_caption(
        obj_id="test-obj-1",
        chunk_idx=0,
        total_chunks=1,
        filename="Documents/report.pdf",
        total_size=1024,
        content_type="application/pdf",
        sha256="abc123",
        secret=None,
    )
    assert cap.startswith("anbar:v1:p:")

    meta = decode_chunk_caption(cap, secret=None)
    assert meta is not None
    assert meta["id"] == "test-obj-1"
    assert meta["i"] == 0
    assert meta["fn"] == "Documents/report.pdf"
    assert meta["sz"] == 1024
    assert meta["ct"] == "application/pdf"
    assert meta["h"] == "abc123"


def test_encode_decode_encrypted():
    secret = "my-secure-master-secret-key-321"
    cap = encode_chunk_caption(
        obj_id="enc-obj-99",
        chunk_idx=1,
        total_chunks=3,
        filename="Secrets/vault.kdbx",
        total_size=50000000,
        content_type="application/octet-stream",
        sha256="def456",
        secret=secret,
    )
    assert cap.startswith("anbar:v1:e:")

    # Decoding with correct secret succeeds
    meta = decode_chunk_caption(cap, secret=secret)
    assert meta is not None
    assert meta["id"] == "enc-obj-99"
    assert meta["i"] == 1
    assert meta["n"] == 3
    assert meta["fn"] == "Secrets/vault.kdbx"
    assert meta["sz"] == 50000000

    # Decoding with wrong secret returns None
    assert decode_chunk_caption(cap, secret="wrong-secret-key-000") is None
    # Decoding without secret returns None
    assert decode_chunk_caption(cap, secret=None) is None


def test_meta_event_encode_decode():
    secret = "meta-secret-999"
    evt = {"op": "rn_dir", "old": "OldFolder", "new": "NewFolder", "ts": 1788000000}

    # Encrypted meta event
    encoded_enc = encode_meta_event(evt, secret=secret)
    assert encoded_enc.startswith("anbar:v1:evt:e:")
    decoded_enc = decode_meta_event(encoded_enc, secret=secret)
    assert decoded_enc is not None
    assert decoded_enc["op"] == "rn_dir"
    assert decoded_enc["old"] == "OldFolder"
    assert decoded_enc["new"] == "NewFolder"

    # Plain meta event
    encoded_plain = encode_meta_event(evt, secret=None)
    assert encoded_plain.startswith("anbar:v1:evt:p:")
    decoded_plain = decode_meta_event(encoded_plain, secret=None)
    assert decoded_plain is not None
    assert decoded_plain["op"] == "rn_dir"

    # Batched delete event
    evt_batch = {"op": "del_batch", "ids": ["id1", "id2", "id3"], "ts": 1788000000}
    enc_batch = encode_meta_event(evt_batch, secret=secret)
    dec_batch = decode_meta_event(enc_batch, secret=secret)
    assert dec_batch is not None
    assert dec_batch["op"] == "del_batch"
    assert dec_batch["ids"] == ["id1", "id2", "id3"]


def test_decode_invalid_caption():
    assert decode_chunk_caption("random message in telegram channel", secret="sec") is None
    assert decode_chunk_caption("anbar:v1:e:corrupt_base64_payload", secret="sec") is None
    assert decode_chunk_caption("anbar:v2:unknown_version", secret="sec") is None


def test_disaster_recovery_rebuild_database(tmp_path):
    db = Database(tmp_path / "disaster_recovery_test.db")
    secret = "hospital-master-encryption-key-777"

    # File 1: Single chunk, unencrypted
    cap1 = encode_chunk_caption(
        obj_id="obj_img_1",
        chunk_idx=0,
        total_chunks=1,
        filename="Photos/summer.jpg",
        total_size=2048,
        content_type="image/jpeg",
        secret=None,
    )
    # File 2: Multi-chunk (2 chunks), encrypted
    cap2_0 = encode_chunk_caption(
        obj_id="obj_vid_2",
        chunk_idx=0,
        total_chunks=2,
        filename="Videos/trip.mp4",
        total_size=32000000,
        content_type="video/mp4",
        secret=secret,
    )
    cap2_1 = encode_chunk_caption(
        obj_id="obj_vid_2",
        chunk_idx=1,
        total_chunks=2,
        filename="Videos/trip.mp4",
        total_size=32000000,
        content_type="video/mp4",
        secret=secret,
    )

    # Raw messages collected from Telegram channel
    messages = [
        {"caption": cap2_1, "file_id": "tg_fid_vid_part1", "message_id": 102, "size": 16000000},
        {"caption": cap1, "file_id": "tg_fid_img", "message_id": 100, "size": 2048},
        {"caption": "normal admin message", "file_id": "msg_plain", "message_id": 101, "size": 10},
        {"caption": cap2_0, "file_id": "tg_fid_vid_part0", "message_id": 103, "size": 16000000},
    ]

    # Process and decode collected messages
    collected_chunks: dict[str, list[dict]] = {}
    for m in messages:
        meta = decode_chunk_caption(m["caption"], secret=secret)
        if not meta:
            continue
        obj_id = str(meta.get("id") or meta.get("fn") or "unk")
        collected_chunks.setdefault(obj_id, []).append(
            {
                "meta": meta,
                "file_id": m["file_id"],
                "message_id": m["message_id"],
                "size": m["size"],
                "backend": "mtproto",
            }
        )

    result = rebuild_from_manifests(collected_chunks, db)

    assert result["recovered_objects"] == 2
    assert result["total_chunks_scanned"] == 3

    # Check recovered objects in DB
    obj1 = db.get_object("obj_img_1")
    assert obj1 is not None
    assert obj1["filename"] == "Photos/summer.jpg"
    assert obj1["content_type"] == "image/jpeg"
    assert obj1["size"] == 2048

    obj2 = db.get_object("obj_vid_2")
    assert obj2 is not None
    assert obj2["filename"] == "Videos/trip.mp4"
    assert obj2["content_type"] == "video/mp4"
    man2 = Manifest.from_json(obj2["manifest"])
    assert len(man2.chunks) == 2
    assert man2.chunks[0].file_id == "tg_fid_vid_part0"
    assert man2.chunks[1].file_id == "tg_fid_vid_part1"


def test_disaster_recovery_with_folder_rename_and_events(tmp_path):
    db = Database(tmp_path / "disaster_recovery_test_events.db")
    secret = "hospital-master-encryption-key-777"

    # 1. Chunk captions
    cap_img = encode_chunk_caption(
        obj_id="obj_img_1",
        chunk_idx=0,
        total_chunks=1,
        filename="TestFolder/photo.jpg",
        total_size=2048,
        content_type="image/jpeg",
        secret=secret,
    )
    cap_doc = encode_chunk_caption(
        obj_id="obj_doc_2",
        chunk_idx=0,
        total_chunks=1,
        filename="TestFolder/readme.txt",
        total_size=512,
        content_type="text/plain",
        secret=secret,
    )

    # 2. Later events: Rename folder "TestFolder" -> "ArchiveFolder" and delete "obj_doc_2"
    evt_rename_folder = encode_meta_event(
        {"op": "rn_dir", "old": "TestFolder", "new": "ArchiveFolder", "ts": 1000},
        secret=secret,
    )
    evt_delete_doc = encode_meta_event(
        {"op": "del_obj", "id": "obj_doc_2", "ts": 2000},
        secret=secret,
    )

    messages = [
        {"text": None, "caption": cap_img, "file_id": "fid_img", "msg_id": 1, "size": 2048},
        {"text": None, "caption": cap_doc, "file_id": "fid_doc", "msg_id": 2, "size": 512},
        {"text": evt_rename_folder, "caption": None, "file_id": None, "msg_id": 3, "size": 0},
        {"text": evt_delete_doc, "caption": None, "file_id": None, "msg_id": 4, "size": 0},
    ]

    collected_chunks: dict[str, list[dict]] = {}
    collected_events: list[dict] = []

    for m in messages:
        # Check event
        if m["text"]:
            e = decode_meta_event(m["text"], secret=secret)
            if e:
                collected_events.append(e)
                continue
        # Check chunk
        if m["caption"]:
            meta = decode_chunk_caption(m["caption"], secret=secret)
            if meta:
                obj_id = str(meta.get("id") or "unk")
                collected_chunks.setdefault(obj_id, []).append(
                    {
                        "meta": meta,
                        "file_id": m["file_id"],
                        "message_id": m["msg_id"],
                        "size": m["size"],
                        "backend": "mtproto",
                    }
                )

    result = rebuild_from_manifests(collected_chunks, db, events=collected_events)

    assert result["recovered_objects"] == 2
    assert result["events_replayed"] == 2

    # obj_img_1 should now be under "ArchiveFolder/photo.jpg"
    img_obj = db.get_object("obj_img_1")
    assert img_obj is not None
    assert img_obj["filename"] == "ArchiveFolder/photo.jpg"

    # obj_doc_2 was deleted by event
    doc_obj = db.get_object("obj_doc_2")
    assert doc_obj is None
