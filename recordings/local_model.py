"""The pinned local model and its sampling, for the recordings in this folder. Recordings run here, never in a reader's
book build: they need llama-cpp-python and the model file (about 2.5 GB, not in the book).

The model file is looked up in the folder named by the RE_MODELS environment variable, else in the models folder
of the machine's scratch area. Its location is never written into a file: a manifest records only the file's
name and sha256.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOOK / "examples"))

from lib.models import LlamaModel  # noqa: E402  (after the path is set; lib fixes threads and seeds on import)

REPO = "unsloth/Qwen3-4B-Instruct-2507-GGUF"
REVISION = "a06e946bb6b655725eafa393f4a9745d460374c9"
FILE = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
FILE_SHA256 = "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597"
QUANTIZATION = "Q4_K_M"
THREADS = 4  # the recording's count; the kit's THREADS (2) applies to the examples
N_CTX = 8192
MAX_TOKENS = 1024
TEMPERATURE = 0
TOP_K = 1
SEED = 4217


def models_dir() -> Path:
    """The folder that holds the model file: RE_MODELS if set, else the models folder in the scratch area."""
    if os.environ.get("RE_MODELS"):
        return Path(os.environ["RE_MODELS"])
    return Path.home() / "scratch" / "models"


def model_file() -> Path:
    return models_dir() / FILE


def file_sha256(path: Path) -> str:
    """The sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_fields() -> dict:
    """The model fields for a recording's manifest. Checks the file's sha256 first and stops if it differs."""
    path = model_file()
    if not path.is_file():
        raise FileNotFoundError(f"the model file {FILE} is not in the models folder")
    actual = file_sha256(path)
    if actual != FILE_SHA256:
        raise ValueError(f"the model file's sha256 differs from the pin (file {FILE})")
    return {
        "model": REPO,
        "model_version": REVISION,
        "file": FILE,
        "file_sha256": FILE_SHA256,
        "quantization": QUANTIZATION,
        "threads": THREADS,
        "n_ctx": N_CTX,
        "max_tokens": MAX_TOKENS,
        "sampling": {"temperature": TEMPERATURE, "top_k": TOP_K, "seed": SEED},
    }


def live_model() -> LlamaModel:
    """The pinned model, loaded with the recording's settings."""
    return LlamaModel(model_file(), n_ctx=N_CTX, n_threads=THREADS, seed=SEED, max_tokens=MAX_TOKENS)
