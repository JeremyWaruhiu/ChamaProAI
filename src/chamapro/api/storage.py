"""Where interview audio is kept, chosen by STORAGE_BACKEND.

    local     data/uploads/<interview_id>/ (CHAMAPRO_UPLOADS), as before
    supabase  a private Supabase Storage bucket (SUPABASE_BUCKET); replay is a
              redirect to a signed URL that expires in SUPABASE_SIGNED_URL_SECONDS

responses.audio_path holds the reference save() returned: an absolute file
path for local (so rows from before this module still work), or
supabase://<bucket>/<key>. Each reference is read by the backend that wrote
it, whichever is configured now, so switching backends strands nothing.

Transcription needs a file on disk. The upload is converted to WAV locally
either way; with Supabase that file stays only as a cache for the worker,
which releases it once the clip is transcribed, and is downloaded again if a
retry needs it.

The service-role key is read from the environment by the server only; it
never appears in a response, and signed URLs carry no key.
"""
from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from chamapro import config

log = logging.getLogger("chamapro.storage")

SUPABASE_SCHEME = "supabase://"


def clip_key(interview_id: int, response_id: int, sentence_no: int) -> str:
    return f"{interview_id}/response_{response_id}_s{sentence_no:02d}.wav"


class AudioStorage(ABC):
    @abstractmethod
    def save(self, wav: Path, key: str) -> str:
        """Store the converted clip under key; returns the reference to keep."""

    @abstractmethod
    def local_path(self, ref: str) -> Path:
        """A file on disk holding the clip, for transcription."""

    def release(self, ref: str) -> None:
        """The worker is done with local_path(ref)."""

    @abstractmethod
    def delete(self, ref: str) -> None:
        """Remove the clip. Missing is not an error."""

    def signed_url(self, ref: str) -> str | None:
        """A short-lived URL to replay the clip, or None when the API serves
        the file itself (local_path)."""
        return None


class LocalStorage(AudioStorage):
    def __init__(self, root: Path):
        self.root = root

    def save(self, wav: Path, key: str) -> str:
        dst = self.root / key
        if wav.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(wav, dst)
        return str(dst)

    def local_path(self, ref: str) -> Path:
        return Path(ref)

    def delete(self, ref: str) -> None:
        Path(ref).unlink(missing_ok=True)


class SupabaseStorage(AudioStorage):
    """A private bucket. `client` is a supabase-py Client; tests pass a fake."""

    def __init__(self, client, bucket: str, cache_dir: Path,
                 signed_url_seconds: int = config.SUPABASE_SIGNED_URL_SECONDS):
        self.client, self.bucket, self.cache_dir = client, bucket, cache_dir
        self.signed_url_seconds = signed_url_seconds

    @classmethod
    def from_config(cls) -> SupabaseStorage:
        if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
            raise RuntimeError("STORAGE_BACKEND=supabase needs SUPABASE_URL and "
                               "SUPABASE_SERVICE_ROLE_KEY in the server's environment")
        from supabase import create_client
        client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        return cls(client, config.SUPABASE_BUCKET, config.UPLOADS_DIR)

    def _bucket(self):
        return self.client.storage.from_(self.bucket)

    def ref(self, key: str) -> str:
        return f"{SUPABASE_SCHEME}{self.bucket}/{key}"

    def split(self, ref: str) -> tuple[str, str]:
        """(bucket, key) of a reference this backend wrote."""
        if not ref.startswith(SUPABASE_SCHEME):
            raise ValueError(f"not a Supabase audio reference: {ref!r}")
        bucket, _, key = ref[len(SUPABASE_SCHEME):].partition("/")
        if bucket != self.bucket or not key or ".." in key.split("/"):
            raise ValueError(f"audio reference {ref!r} is not in bucket {self.bucket!r}")
        return bucket, key

    def _cache(self, key: str) -> Path:
        return self.cache_dir / key

    def save(self, wav: Path, key: str) -> str:
        self._bucket().upload(key, wav.read_bytes(),
                              {"content-type": "audio/wav", "upsert": "false"})
        cache = self._cache(key)
        if wav.resolve() != cache.resolve():
            cache.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(wav, cache)
        return self.ref(key)

    def local_path(self, ref: str) -> Path:
        _, key = self.split(ref)
        cache = self._cache(key)
        if not cache.is_file():
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(self._bucket().download(key))
        return cache

    def release(self, ref: str) -> None:
        _, key = self.split(ref)
        self._cache(key).unlink(missing_ok=True)

    def delete(self, ref: str) -> None:
        _, key = self.split(ref)
        self._bucket().remove([key])
        self._cache(key).unlink(missing_ok=True)

    def signed_url(self, ref: str) -> str | None:
        _, key = self.split(ref)
        out = self._bucket().create_signed_url(key, self.signed_url_seconds)
        url = out.get("signedURL") or out.get("signedUrl")
        if not url:
            raise RuntimeError(f"Supabase returned no signed URL for {key}")
        return url


_backends: dict[str, AudioStorage] = {}


def _get(name: str) -> AudioStorage:
    if name not in _backends:
        if name == "local":
            _backends[name] = LocalStorage(config.UPLOADS_DIR)
        elif name == "supabase":
            _backends[name] = SupabaseStorage.from_config()
        else:
            raise RuntimeError(f"STORAGE_BACKEND must be local or supabase, not {name!r}")
    return _backends[name]


def backend() -> AudioStorage:
    """The configured backend: where new clips go."""
    return _get(config.STORAGE_BACKEND)


def for_ref(ref: str) -> AudioStorage:
    """The backend that wrote this reference."""
    return _get("supabase" if ref.startswith(SUPABASE_SCHEME) else "local")


def use(name: str, store: AudioStorage) -> None:
    """Install a backend instance (tests; a server with a custom client)."""
    _backends[name] = store


def reset() -> None:
    _backends.clear()
