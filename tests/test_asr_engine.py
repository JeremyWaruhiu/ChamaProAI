"""scripts/transcribe.py: engine and device fallback, the generation cap, and
the decoding safeguards. No real model is loaded."""
from types import SimpleNamespace

import pytest

import transcribe  # scripts/ is on sys.path via chamapro.api.pipeline

from conftest import FakeASR, wait_until


@pytest.fixture
def export(tmp_path):
    """A directory that passes for an OpenVINO export."""
    (tmp_path / "openvino_encoder_model.xml").write_text("<net/>")
    (tmp_path / "openvino_config.json").write_text(
        '{"quantization_config": {"processor": "microsoft/paza-whisper-large-v3-turbo"}}')
    return tmp_path


@pytest.fixture
def engines(monkeypatch):
    """Stub both loaders; .asked records what was loaded, .broken lists
    OpenVINO devices that fail to compile."""
    st = SimpleNamespace(asked=[], broken=set())

    def ov(model_dir, device):
        st.asked.append(("openvino", device))
        if device in st.broken:
            raise RuntimeError(f"{device} compile failed")
        return f"ov-{device}"

    def torch(name):
        st.asked.append(("torch", name))
        return "torch-pipe"

    monkeypatch.setattr(transcribe, "load_openvino", ov)
    monkeypatch.setattr(transcribe, "load_torch", torch)
    monkeypatch.setattr(transcribe, "torch_device", lambda: -1)
    monkeypatch.setattr(transcribe, "openvino_devices", lambda: ["CPU", "GPU"])
    return st


def load(engine, device, ov_dir, **kw):
    logs = []
    asr = transcribe.load_asr("hf/model", engine, device, ov_dir, log=logs.append, **kw)
    return asr, logs


def test_openvino_on_the_gpu(engines, export):
    asr, logs = load("openvino", "GPU", export)
    assert (asr.engine, asr.device, asr.pipe) == ("openvino", "GPU", "ov-GPU")
    assert asr.label == "microsoft/paza-whisper-large-v3-turbo (openvino GPU)"
    assert logs == [f"ASR: engine=openvino device=GPU model={export}"]


def test_no_gpu_falls_back_to_cpu(engines, export, monkeypatch):
    monkeypatch.setattr(transcribe, "openvino_devices", lambda: ["CPU"])
    asr, logs = load("openvino", "GPU", export)
    assert (asr.engine, asr.device) == ("openvino", "CPU")
    assert engines.asked == [("openvino", "CPU")]
    assert "no GPU; falling back to CPU" in logs[0]


def test_gpu_that_fails_to_compile_falls_back_to_cpu(engines, export):
    engines.broken = {"GPU"}
    asr, logs = load("openvino", "GPU", export)
    assert (asr.engine, asr.device) == ("openvino", "CPU")
    assert engines.asked == [("openvino", "GPU"), ("openvino", "CPU")]
    assert "GPU failed (RuntimeError: GPU compile failed); falling back to CPU" in logs[0]


def test_missing_export_falls_back_to_torch(engines, tmp_path):
    asr, logs = load("openvino", "GPU", tmp_path / "nothing-here")
    assert (asr.engine, asr.device, asr.model, asr.label) == ("torch", "CPU", "hf/model", "hf/model")
    assert engines.asked == [("torch", "hf/model")]
    assert "no OpenVINO model in" in logs[0] and "falling back to torch hf/model" in logs[0]


def test_broken_openvino_falls_back_to_torch(engines, export):
    engines.broken = {"GPU", "CPU"}
    asr, logs = load("openvino", "GPU", export)
    assert asr.engine == "torch"
    assert any("OpenVINO failed" in m for m in logs)


def test_torch_engine_ignores_the_export(engines, export):
    asr, _ = load("torch", "GPU", export)
    assert (asr.engine, asr.device) == ("torch", "CPU")
    assert engines.asked == [("torch", "hf/model")]


@pytest.mark.parametrize("broken, devices, ov_dir", [
    (set(), ["CPU"], "export"),          # no GPU
    ({"GPU"}, ["CPU", "GPU"], "export"),  # GPU fails
    (set(), ["CPU", "GPU"], "missing"),  # no export
])
def test_without_fallback_failures_raise(engines, export, tmp_path, monkeypatch, broken, devices, ov_dir):
    engines.broken = broken
    monkeypatch.setattr(transcribe, "openvino_devices", lambda: devices)
    with pytest.raises(Exception):
        load("openvino", "GPU", export if ov_dir == "export" else tmp_path / "x", fallback=False)
    assert ("torch", "hf/model") not in engines.asked


def test_unknown_engine_is_refused():
    with pytest.raises(ValueError, match="unknown ASR engine"):
        transcribe.load_asr("m", "onnx", "CPU")


# --- Generation cap and decoding ------------------------------------------------

def test_token_cap_scales_with_the_clip_and_has_a_ceiling():
    assert transcribe.token_cap(0) == transcribe.TOKENS_BASE
    assert transcribe.token_cap(4.0) == 16 + 48
    assert transcribe.token_cap(4.0, tokens_per_second=6) == 16 + 24
    assert transcribe.token_cap(4.01) == 65                         # rounds up
    assert transcribe.token_cap(600) == transcribe.MAX_NEW_TOKENS   # Whisper's decoder limit


def test_timestamped_decoding_keeps_every_safeguard(wav):
    fake = FakeASR()
    transcribe.transcribe_clip(wav, fake, "sw", duration=4.0)
    kw = fake.kwargs[0]
    assert kw["return_timestamps"] is True
    assert kw["generate_kwargs"] == {"language": "sw", "task": "transcribe",
                                     "condition_on_prev_tokens": False, "max_new_tokens": 64}


def test_plain_decoding_has_the_cap_and_no_timestamps(wav):
    fake = FakeASR()
    transcribe.transcribe_clip(wav, fake, "sw", duration=4.0, decoding="plain", tokens_per_second=6)
    kw = fake.kwargs[0]
    assert "return_timestamps" not in kw
    assert kw["generate_kwargs"]["max_new_tokens"] == 40
    assert kw["generate_kwargs"]["condition_on_prev_tokens"] is False


def test_unknown_decoding_is_refused(wav):
    with pytest.raises(ValueError, match="unknown decoding"):
        transcribe.transcribe_clip(wav, FakeASR(), "sw", duration=1, decoding="beam")


def test_chunks_starting_after_the_clip_end_are_dropped(wav):
    def pipe(path, **kw):
        return {"text": "one two three", "chunks": [
            {"text": "one", "timestamp": (0.0, 1.0)}, {"text": " two", "timestamp": (1.0, 2.9)},
            {"text": " three", "timestamp": (3.0, 6.0)}]}
    assert transcribe.transcribe_clip(wav, pipe, "sw", duration=3.0)["text"] == "one two"


def test_duration_is_read_from_the_file_when_not_given(wav):
    fake = FakeASR()
    transcribe.transcribe_clip(wav, fake, "sw")                     # the fixture clip is 1 s
    assert fake.kwargs[0]["generate_kwargs"]["max_new_tokens"] == transcribe.token_cap(1.0)


def test_the_worker_caps_by_clip_length(client, asr, interview, upload, state):
    upload(interview, 1)
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    gen = asr.kwargs[0]["generate_kwargs"]
    assert gen["max_new_tokens"] == transcribe.token_cap(1.0)
    assert asr.kwargs[0]["return_timestamps"] is True                # the default stays
