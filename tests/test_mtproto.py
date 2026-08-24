"""F5: MTProto backend contract with a mock Telethon client + wiring."""
from __future__ import annotations

import io

import pytest

from anbar.config import Backend, Settings
from anbar.main import _default_backend
from anbar.storage import MTProtoBackend, ObjectRef


class _Doc:
    def __init__(self, doc_id: int):
        self.id = doc_id


class _Media:
    def __init__(self, doc_id: int):
        self.document = _Doc(doc_id)


class _Msg:
    def __init__(self, msg_id: int, doc_id: int, data: bytes):
        self.id = msg_id
        self.media = _Media(doc_id)
        self._data = data


class _RawOk:
    """Stand-in for a BoolTrue RPC response."""

    def __bool__(self) -> bool:
        return True


class FakeClient:
    """Just enough of the Telethon client surface for MTProtoBackend."""

    def __init__(self, authorized: bool = True) -> None:
        self._authorized = authorized
        self._msgs: dict[int, _Msg] = {}
        self._next_id = 1
        self.started = False
        self.disconnected = False
        self._parts: dict[tuple[int, int], bytes] = {}
        self._last_upload = b""

    async def start(self) -> None:
        self.started = True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_user_authorized(self) -> bool:
        return self._authorized

    async def get_entity(self, peer):
        return ("entity", peer)

    async def send_file(self, entity, file, file_name: str = "", **kw) -> _Msg:
        msg_id = self._next_id
        self._next_id += 1
        if isinstance(file, io.BytesIO):
            file.seek(0)
            payload = file.read()
        elif isinstance(file, bytes):
            payload = file
        elif hasattr(file, "id") and hasattr(file, "parts"):
            # InputFileBig handle from _upload_parallel: reassemble parts
            fid = file.id
            payload = b"".join(
                self._parts.get((fid, i * 524288), b"")
                for i in range(file.parts)
            )
        else:
            payload = self._last_upload
        self._msgs[msg_id] = _Msg(msg_id, msg_id, payload)
        return self._msgs[msg_id]

    async def upload_file(self, file, file_size: int | None = None,
                          part_size_kb: float | None = None, **kw):
        if isinstance(file, io.BytesIO):
            file.seek(0)
            self._last_upload = file.read()
        else:
            self._last_upload = b""

    def __call__(self, request):
        """Support `client(SaveBigFilePartRequest(...))` raw API calls."""
        from telethon.tl.functions.upload import SaveBigFilePartRequest

        if isinstance(request, SaveBigFilePartRequest):
            start = request.file_part * len(request.bytes)
            self._parts[(request.file_id, start)] = request.bytes

            async def _ok():
                return _RawOk()

            return _ok()
        raise AssertionError(f"unexpected request {request!r}")

    async def get_messages(self, entity, ids=None, **kw):
        mid = ids if not isinstance(ids, (list, tuple)) else ids[0]
        return self._msgs.get(mid)

    def iter_download(self, msg, request_size: int = 1048576):
        async def _gen():
            yield msg._data
        return _gen()

    async def delete_messages(self, entity, message_id: int) -> None:
        self._msgs.pop(message_id, None)


def _backend(client: FakeClient, session_file: str = "/tmp/x.session") -> MTProtoBackend:
    return MTProtoBackend(api_id=1, api_hash="h", session_file=session_file,
                          client=client)


def _touch(path: str) -> str:
    with open(path, "wb") as f:
        f.write(b"fake-auth-key")
    return path


async def test_store_open_delete_roundtrip(tmp_path):
    client = FakeClient()
    sess = _touch(str(tmp_path / "session.session"))
    be = _backend(client, session_file=sess)
    await be.connect()
    assert client.started

    ref = await be.store(b"hello mtproto", "blob.bin")
    assert ref.backend == "mtproto"
    assert ref.message_id is not None
    assert ref.file_id == str(ref.message_id)
    assert ref.size == len(b"hello mtproto")

    got = await be.open(ref)
    assert got == b"hello mtproto"

    assert await be.delete(ref) is True
    # message is gone: get_message returns None → open raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        await be.open(ref)

    await be.close()
    assert client.disconnected


async def test_health_reflects_authorization():
    assert await _backend(FakeClient(authorized=True)).health() is True
    assert await _backend(FakeClient(authorized=False)).health() is False


async def test_connect_missing_session_file_fails(tmp_path):
    be = _backend(FakeClient(), session_file=str(tmp_path / "nope.session"))
    with pytest.raises(RuntimeError, match="session file not found"):
        await be.connect()


async def test_connect_failure_raises_helpful_error(tmp_path):
    client = FakeClient()
    sess = _touch(str(tmp_path / "session.session"))

    async def boom() -> None:
        raise EOFError

    client.start = boom  # type: ignore[method-assign]
    be = _backend(client, session_file=sess)
    with pytest.raises(RuntimeError, match="anbarctl login"):
        await be.connect()


async def test_delete_without_message_id_is_noop():
    be = _backend(FakeClient())
    assert await be.delete(ObjectRef(file_id="1", backend="mtproto")) is False


async def test_default_backend_wires_mtproto():
    settings = Settings(backend=Backend.MTPROTO, api_id=123, api_hash="abc",
                        session_file="/tmp/s.session", env_file=None)
    be = _default_backend(settings)
    assert isinstance(be, MTProtoBackend)
    assert be.max_upload_bytes == 2 * 1024 * 1024 * 1024


async def test_default_backend_mtproto_requires_creds():
    settings = Settings(backend=Backend.MTPROTO, env_file=None)
    with pytest.raises(RuntimeError, match="ANBAR_API_ID"):
        _default_backend(settings)


async def test_chunk_size_backend_aware():
    bot = Settings(backend=Backend.BOT, chunk_size_mb=16, env_file=None)
    assert bot.chunk_size == 16 * 1024 * 1024

    # default 16 MB stays 16 MB even under mtproto (cap is higher, not a floor)
    mp16 = Settings(backend=Backend.MTPROTO, chunk_size_mb=16, env_file=None)
    assert mp16.chunk_size == 16 * 1024 * 1024

    # large configured chunk grows under mtproto but is capped at 49 MB (default cap)
    mp64 = Settings(backend=Backend.MTPROTO, chunk_size_mb=64, env_file=None)
    assert mp64.chunk_size == 49 * 1024 * 1024

    # the mtproto cap itself is configurable
    mp256 = Settings(
        backend=Backend.MTPROTO, chunk_size_mb=256,
        mtproto_chunk_cap_mb=256, env_file=None,
    )
    assert mp256.chunk_size == 256 * 1024 * 1024

    # configured value below the raised cap still wins (cap never raises)
    mp128 = Settings(
        backend=Backend.MTPROTO, chunk_size_mb=128,
        mtproto_chunk_cap_mb=256, env_file=None,
    )
    assert mp128.chunk_size == 128 * 1024 * 1024

    # same config under bot is capped at 19 MB
    bot64 = Settings(backend=Backend.BOT, chunk_size_mb=64, env_file=None)
    assert bot64.chunk_size == 19 * 1024 * 1024