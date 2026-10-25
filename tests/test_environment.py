"""The installed environment matches the pins in requirements.txt.

A torchvision that does not match torch once broke `from transformers import
pipeline`; these imports catch that before any model is loaded.
"""
import re
from importlib import metadata

from chamapro import config


def test_transformers_pipeline_imports():
    from transformers import pipeline
    assert callable(pipeline)


def test_torchvision_imports_against_this_torch():
    import torch
    import torchvision
    assert torchvision.__version__ and torch.__version__
    # torchvision's compiled ops load only against the torch it was built for
    assert torch.ops.torchvision.nms is not None


def pins():
    text = (config.PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Za-z0-9_.\-]+)==(\S+)", text, flags=re.M))


def test_pinned_packages_are_installed_at_their_pins():
    expected = pins()
    for name in ("torch", "torchvision", "transformers", "numpy", "openvino",
                 "optimum-intel", "nncf"):
        assert name in expected, f"{name} is not pinned"
    wrong = {n: (v, metadata.version(n)) for n, v in expected.items() if metadata.version(n) != v}
    assert wrong == {}, "installed versions differ from requirements.txt (pinned, installed)"
