"""Audio storage: LocalStorage (data/uploads) and SupabaseStorage (a private
bucket) behind one interface. Supabase is a fake client here: no network."""
import pytest

from chamapro import config
from chamapro.api import pipeline as pl
from chamapro.api import storage

from conftest import loaded, wait_until


class FakeBucket:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def upload(self, path, file, file_options=None):
        self.store.calls.append(("upload", self.name, path, file_options))
        if self.store.down:
            raise ConnectionError("supabase unreachable")
        self.store.objects[(self.name, path)] = bytes(file)
        return {"path": path}

    def download(self, path, options=None, query_params=None):
        self.store.calls.append(("download", self.name, path))
        return self.store.objects[(self.name, path)]

    def remove(self, paths):
        self.store.calls.append(("remove", self.name, list(paths)))
        for p in paths:
            self.store.objects.pop((self.name, p), None)
        return []

    def create_signed_url(self, path, expires_in, options=None):
        self.store.calls.append(("sign", self.name, path, expires_in))
        return {"signedURL": f"https://project.supabase.co/storage/v1/object/sign/{self.name}/"
                             f"{path}?token=t&expires={expires_in}",
                "signedUrl": "ignored"}


class FakeSupabase:
    """The slice of supabase-py's Client that SupabaseStorage uses."""

    def __init__(self):
        self.objects, self.calls, self.down = {}, [], False
        self.storage = self

    def from_(self, bucket):
        return FakeBucket(self, bucket)


@pytest.fixture
def fake():
    return FakeSupabase()


@pytest.fixture
def supa(fake, tmp_path):
    return storage.SupabaseStorage(fake, "interview-audio", tmp_path / "cache", signed_url_seconds=60)


@pytest.fixture
def wav_bytes(tmp_path, wav):
    p = tmp_path / "clip.wav"
    p.write_bytes(wav.read_bytes())
    return p


# --- LocalStorage -----------------------------------------------------------------

def test_local_keeps_the_absolute_path(tmp_path, wav_bytes):
    local = storage.LocalStorage(tmp_path / "uploads")
    ref = local.save(wav_bytes, "7/response_1_s01.wav")
    assert ref == str(tmp_path / "uploads/7/response_1_s01.wav") and not wav_bytes.exists()
    assert local.local_path(ref).read_bytes()[:4] == b"RIFF"
    assert local.signed_url(ref) is None                 # the API serves the file itself
    local.release(ref)
    assert local.local_path(ref).exists()                # release keeps local files
    local.delete(ref)
    local.delete(ref)                                    # missing is fine
    assert not local.local_path(ref).exists()


# --- SupabaseStorage ----------------------------------------------------------------

def test_save_uploads_privately_and_keeps_a_cache(supa, fake, wav_bytes, tmp_path):
    data = wav_bytes.read_bytes()
    ref = supa.save(wav_bytes, "7/response_1_s01.wav")
    assert ref == "supabase://interview-audio/7/response_1_s01.wav"
    assert fake.objects[("interview-audio", "7/response_1_s01.wav")] == data
    assert fake.calls[0] == ("upload", "interview-audio", "7/response_1_s01.wav",
                             {"content-type": "audio/wav", "upsert": "false"})
    assert (tmp_path / "cache/7/response_1_s01.wav").read_bytes() == data


def test_local_path_downloads_when_the_cache_is_gone(supa, fake, wav_bytes):
    ref = supa.save(wav_bytes, "7/response_2_s02.wav")
    supa.release(ref)
    assert not supa._cache("7/response_2_s02.wav").exists()
    path = supa.local_path(ref)
    assert path.read_bytes()[:4] == b"RIFF"
    assert ("download", "interview-audio", "7/response_2_s02.wav") in fake.calls


def test_signed_url_is_short_lived_and_carries_no_key(supa, fake, wav_bytes, monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    ref = supa.save(wav_bytes, "7/response_3_s03.wav")
    url = supa.signed_url(ref)
    assert url.startswith("https://project.supabase.co/") and "expires=60" in url
    assert "service-role-secret" not in url
    assert ("sign", "interview-audio", "7/response_3_s03.wav", 60) in fake.calls


def test_delete_removes_remote_and_cache(supa, fake, wav_bytes):
    ref = supa.save(wav_bytes, "7/response_4_s04.wav")
    supa.delete(ref)
    assert fake.objects == {} and not supa._cache("7/response_4_s04.wav").exists()


@pytest.mark.parametrize("ref", ["/abs/path.wav", "supabase://other-bucket/7/x.wav",
                                 "supabase://interview-audio/", "supabase://interview-audio/../x"])
def test_foreign_references_are_refused(supa, ref):
    with pytest.raises(ValueError):
        supa.signed_url(ref)


def test_from_config_needs_url_and_key(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", None)
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", None)
    with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"):
        storage.SupabaseStorage.from_config()


def test_unknown_backend_is_refused(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage, "_backends", {})
    with pytest.raises(RuntimeError, match="local or supabase"):
        storage.backend()


def test_references_pick_their_own_backend(supa, monkeypatch):
    monkeypatch.setattr(storage, "_backends", {"supabase": supa,
                                               "local": storage.LocalStorage(config.UPLOADS_DIR)})
    assert storage.for_ref("supabase://interview-audio/1/a.wav") is supa
    assert isinstance(storage.for_ref("/data/uploads/1/a.wav"), storage.LocalStorage)


# --- Through the API, with STORAGE_BACKEND=supabase ----------------------------------

@pytest.fixture
def on_supabase(monkeypatch, supa, tmp_path):
    cache = config.UPLOADS_DIR                         # where uploads are converted
    supa.cache_dir = cache
    monkeypatch.setattr(config, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(storage, "_backends", {"supabase": supa,
                                               "local": storage.LocalStorage(config.UPLOADS_DIR)})
    return supa


def test_upload_transcribe_replay_delete(client, interview, upload, asr, state, on_supabase, fake):
    r = upload(interview, 3)
    assert r.status_code == 202, r.text
    rid = r.json()["id"]
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    key = f"{interview}/response_{rid}_s03.wav"
    assert ("interview-audio", key) in fake.objects
    assert asr.calls == [f"response_{rid}_s03.wav"]         # transcribed from the cache ...
    assert not (config.UPLOADS_DIR / key).exists()          # ... which was then released

    replay = client.get(f"/api/responses/{rid}/audio", follow_redirects=False)
    assert replay.status_code == 307
    assert replay.headers["location"].startswith("https://project.supabase.co/storage/v1/object/sign/")

    assert client.delete(f"/api/responses/{rid}").status_code == 200
    assert ("interview-audio", key) not in fake.objects


def test_storage_outage_on_upload_is_503_and_writes_nothing(client, interview, upload, asr,
                                                            state, on_supabase, fake):
    fake.down = True
    r = upload(interview, 4)
    assert r.status_code == 503 and "storage" in r.json()["detail"]
    assert state(interview)["responses"] == []
    assert list((config.UPLOADS_DIR / str(interview)).glob("response_*")) == []


def test_old_local_clips_still_replay_after_switching(client, interview, upload, asr, state,
                                                      monkeypatch, supa):
    rid = upload(interview, 5).json()["id"]                  # stored locally
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    monkeypatch.setattr(config, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(storage, "_backends", {"supabase": supa,
                                               "local": storage.LocalStorage(config.UPLOADS_DIR)})
    r = client.get(f"/api/responses/{rid}/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"


def test_worker_reads_through_storage(monkeypatch, supa, fake, wav_bytes, client):
    """A queued clip whose cache was lost is downloaded again for transcription."""
    from chamapro.api.db import Response, SessionLocal
    from conftest import FakeASR, new_interview
    iid = new_interview(client)
    with SessionLocal() as db:
        r = Response(interview_id=iid, sentence_no=6, audio_path="", status="queued")
        db.add(r)
        db.flush()
        r.audio_path = supa.save(wav_bytes, f"{iid}/response_{r.id}_s06.wav")
        db.commit()
        rid = r.id
    supa.release(r.audio_path)
    monkeypatch.setattr(storage, "_backends", {"supabase": supa})
    fake_asr = FakeASR()
    monkeypatch.setattr(pl, "_asr", loaded(fake_asr))
    pl.transcribe_response(rid)
    with SessionLocal() as db:
        assert db.get(Response, rid).status == "transcribed"
    assert fake_asr.calls == [f"response_{rid}_s06.wav"]
    assert ("download", "interview-audio", f"{iid}/response_{rid}_s06.wav") in fake.calls
