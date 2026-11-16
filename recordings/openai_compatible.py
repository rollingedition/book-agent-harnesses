"""Record the OpenAI-compatible adapter against llama.cpp's own server on loopback, for T-01's first step.

    python recordings/openai_compatible.py

Starts ``python -m llama_cpp.server`` with the pinned model (recordings/local_model.py) on 127.0.0.1, on a port the OS
picks. Sends the same first-step request twice through OpenAICompatibleModel. Each exchange, the request as sent and
the raw response body as text, goes into exchanges.jsonl. The server is stopped when the recording ends; its log,
its port and the model's path stay out of the book.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request

import local_model  # sets the path to lib first, then imports the pinned model settings
from recorded import Recording, scratch

from lib.case import load_tasks
from lib.models import MODEL_ALIAS, first_step, loopback_model
from lib.prompts import prompt_sha256
from lib.tools import CH1

REQUESTS = 2
READY_SECONDS = 900
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, no proxy


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_ready(base_url: str) -> None:
    deadline = time.monotonic() + READY_SECONDS
    while True:
        try:
            with OPENER.open(base_url + "/models", timeout=5):
                return
        except OSError:
            if time.monotonic() > deadline:
                raise TimeoutError("the llama.cpp server did not answer") from None
            time.sleep(2)


def main() -> int:
    task = load_tasks(only=["T-01"])[0]
    messages, tools = first_step(task, CH1)
    # the manifest's fields check the model file's sha256 first, so a wrong file stops the run before the server starts
    recording = Recording("openai-compatible", prompt_sha256=prompt_sha256(CH1.system, CH1.descriptions()),
                          tool_set=CH1.name, task=task.id, endpoint="/v1/chat/completions", requests=REQUESTS,
                          server="llama-cpp-python 0.3.36, python -m llama_cpp.server",
                          **local_model.manifest_fields())
    with recording as out, (scratch() / "openai-compatible-server.log").open("w", encoding="utf-8") as log:
        port = free_port()
        base_url = f"http://127.0.0.1:{port}/v1"
        server = subprocess.Popen(
            [sys.executable, "-m", "llama_cpp.server", "--model", str(local_model.model_file()),
             "--model_alias", MODEL_ALIAS, "--host", "127.0.0.1", "--port", str(port),
             "--n_ctx", str(local_model.N_CTX), "--n_threads", str(local_model.THREADS),
             "--seed", str(local_model.SEED)],
            stdout=log, stderr=subprocess.STDOUT)
        rows = []
        try:
            wait_ready(base_url)
            bodies: list[str] = []
            model = loopback_model(base_url, on_body=bodies.append)
            for _ in range(REQUESTS):
                model.reply(messages, tools)
                rows.append({"request": model.request_body(messages, tools), "response": bodies[-1]})
        finally:
            server.terminate()
            server.wait(timeout=60)
        (out / "exchanges.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
