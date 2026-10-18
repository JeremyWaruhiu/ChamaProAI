"""GET /api/responses/{id}/audio: replay of a recorded answer."""
import io

import soundfile as sf

from chamapro import config

from conftest import wait_until


def test_audio_is_the_stored_16k_clip(client, interview, upload, audio):
    rid = upload(interview, 3, audio["stereo44k"]).json()["id"]
    r = client.get(f"/api/responses/{rid}/audio")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    stored = config.UPLOADS_DIR / str(interview) / f"response_{rid}_s03.wav"
    assert r.content == stored.read_bytes()
    data, sr = sf.read(io.BytesIO(r.content))
    assert sr == 16000 and data.ndim == 1


def test_audio_supports_seeking(client, interview, upload):
    rid = upload(interview, 1).json()["id"]
    r = client.get(f"/api/responses/{rid}/audio", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100


def test_audio_stays_available_after_assessment(client, assessed_interview, state):
    rid = state(assessed_interview)["responses"][0]["id"]
    assert client.get(f"/api/responses/{rid}/audio").status_code == 200


def test_unknown_response_is_404(client):
    r = client.get("/api/responses/999999/audio")
    assert r.status_code == 404 and r.json() == {"detail": "response 999999 not found"}


def test_deleted_response_audio_is_404(client, interview, upload, state):
    rid = upload(interview, 1).json()["id"]
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    client.delete(f"/api/responses/{rid}")
    assert client.get(f"/api/responses/{rid}/audio").status_code == 404


def test_missing_file_is_404_json(client, interview, upload):
    rid = upload(interview, 1).json()["id"]
    (config.UPLOADS_DIR / str(interview) / f"response_{rid}_s01.wav").unlink()
    r = client.get(f"/api/responses/{rid}/audio")
    assert r.status_code == 404 and r.json() == {"detail": f"audio for response {rid} is missing"}
