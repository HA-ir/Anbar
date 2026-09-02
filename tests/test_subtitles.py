"""FEAT-SUBS: video subtitle tracks — parse, kv storage, API, auth, purge."""

from __future__ import annotations

import pytest

from anbar.subtitles import (
    MAX_TRACKS,
    _meta_from_filename,
    add,
    delete,
    drop_for,
    get_vtt,
    load,
    parse_subtitle,
    public_view,
    update,
)

SRT = (
    "1\n00:00:01,500 --> 00:00:03,000\nHello <b>world</b> & <script>alert(1)</script>\n\n"
    "2\n00:00:05,000 --> 00:00:07,200\nSecond line\n"
)

VTT = "WEBVTT\n\n00:00.000 --> 00:02.000\nHi\n"


def _video(client, name="clip.mp4", body=b"vid"):
    r = client.post(
        "/api/v1/upload",
        files={"file": (name, body, "video/mp4")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_srt_converted_to_vtt_and_sanitized():
    vtt = parse_subtitle("sub.srt", SRT.encode())
    assert vtt.startswith("WEBVTT")
    assert "00:00:01.500 --> 00:00:03.000" in vtt
    # hostile markup is escaped, whitelisted tags survive
    assert "<script>" not in vtt
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in vtt
    assert "<b>world</b>" in vtt


def test_vtt_passthrough_and_rejects():
    assert parse_subtitle("s.vtt", VTT.encode()).startswith("WEBVTT")
    with pytest.raises(ValueError):
        parse_subtitle("s.srt", b"\xff\xfe\x00garbage")
    with pytest.raises(ValueError):
        parse_subtitle("s.srt", "just text no cues".encode())
    with pytest.raises(ValueError):
        parse_subtitle("s.srt", b"x" * (3 * 1024 * 1024))


def test_meta_from_filename():
    assert _meta_from_filename("movie.fa.srt") == ("fa", "movie")
    assert _meta_from_filename("Some.Show.[en-US].vtt") == ("en-us", "Some.Show")
    assert _meta_from_filename("no-lang.vtt") == ("", "no-lang")


def test_track_lifecycle(client):
    obj_id = _video(client)
    # add first track (becomes default), second with ?default=1
    r1 = client.post(
        f"/api/v1/admin/objects/{obj_id}/subs",
        files={"file": ("clip.fa.srt", SRT.encode(), "application/x-subrip")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r1.status_code == 200, r1.text
    t1 = r1.json()["track"]
    assert t1["lang"] == "fa" and t1["default"] is True
    r2 = client.post(
        f"/api/v1/admin/objects/{obj_id}/subs?default=1",
        files={"file": ("clip.en.vtt", VTT.encode(), "text/vtt")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r2.status_code == 200
    t2 = r2.json()["track"]
    # t2 became the single default
    listing = client.get(
        f"/api/v1/admin/objects/{obj_id}/subs", headers={"Authorization": "Bearer test-admin-key"}
    ).json()["tracks"]
    assert [t["id"] for t in listing] == [t1["id"], t2["id"]]
    assert [t["default"] for t in listing] == [False, True]
    # update label/lang
    r3 = client.patch(
        f"/api/v1/admin/objects/{obj_id}/subs/{t1['id']}",
        json={"label": "فارسی", "lang": "fa-IR"},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r3.status_code == 200 and r3.json()["track"]["label"] == "فارسی"
    # fetch VTT via public /f path with bearer auth
    vtt = client.get(
        f"/f/{obj_id}/subs/{t2['id']}", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert vtt.status_code == 200 and vtt.text.startswith("WEBVTT")
    assert vtt.headers["content-type"].startswith("text/vtt")
    # unknown track → 404
    assert (
        client.get(
            f"/f/{obj_id}/subs/nope", headers={"Authorization": "Bearer test-admin-key"}
        ).status_code
        == 404
    )
    # delete default → falls back to first remaining
    r4 = client.delete(
        f"/api/v1/admin/objects/{obj_id}/subs/{t2['id']}",
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r4.status_code == 200
    listing = client.get(
        f"/api/v1/admin/objects/{obj_id}/subs", headers={"Authorization": "Bearer test-admin-key"}
    ).json()["tracks"]
    assert len(listing) == 1 and listing[0]["default"] is True
    # drop_for clears everything
    drop_for(client.app.state.db, obj_id)
    assert load(client.app.state.db, obj_id) == []


def test_default_flag_moves(client):
    obj_id = _video(client)
    for i, fn in enumerate(("a.srt", "b.srt")):
        client.post(
            f"/api/v1/admin/objects/{obj_id}/subs",
            files={"file": (fn, VTT.encode(), "text/vtt")},
            headers={"Authorization": "Bearer test-admin-key"},
        )
    tracks = public_view(load(client.app.state.db, obj_id))
    r = client.patch(
        f"/api/v1/admin/objects/{obj_id}/subs/{tracks[1]['id']}",
        json={"default": True},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert r.status_code == 200
    tracks = public_view(load(client.app.state.db, obj_id))
    assert [t["default"] for t in tracks] == [False, True]
    assert delete(client.app.state.db, obj_id, tracks[1]["id"]) is True
    tracks = public_view(load(client.app.state.db, obj_id))
    assert tracks[0]["default"] is True
    assert get_vtt(client.app.state.db, obj_id, "missing") is None


def test_max_tracks(client):
    obj_id = _video(client)
    for i in range(MAX_TRACKS):
        add(client.app.state.db, obj_id, f"s{i}.srt", VTT.encode())
    with pytest.raises(ValueError):
        add(client.app.state.db, obj_id, "extra.srt", VTT.encode())


def test_auth_enforced_on_subs(client):
    obj_id = _video(client)
    client.post(
        f"/api/v1/admin/objects/{obj_id}/subs",
        files={"file": ("c.srt", SRT.encode(), "application/x-subrip")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    # no auth → 401 on both endpoints
    assert client.get(f"/f/{obj_id}/subs").status_code == 401
    # uploader key may also view media; bearer admin works
    ok = client.get(f"/f/{obj_id}/subs", headers={"Authorization": "Bearer test-admin-key"})
    assert ok.status_code == 200
    # admin API requires admin
    assert (
        client.get(f"/api/v1/admin/objects/{obj_id}/subs", headers={"Authorization": "Bearer test-key"}).status_code
        == 403
    )
    # unknown object → 404
    r = client.get("/f/missing/subs", headers={"Authorization": "Bearer test-admin-key"})
    assert r.status_code == 404


def test_purge_drops_subs(client):
    obj_id = _video(client)
    client.post(
        f"/api/v1/admin/objects/{obj_id}/subs",
        files={"file": ("c.srt", SRT.encode(), "application/x-subrip")},
        headers={"Authorization": "Bearer test-admin-key"},
    )
    assert load(client.app.state.db, obj_id)
    # hard-delete the object (trash purge)
    r = client.delete(
        f"/f/{obj_id}?purge=true", headers={"Authorization": "Bearer test-admin-key"}
    )
    assert r.status_code in (200, 410), r.text
    assert load(client.app.state.db, obj_id) == []
