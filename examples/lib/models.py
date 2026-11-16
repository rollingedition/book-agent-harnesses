"""The models the loop talks to, and the raw-text format their tool calls come in.

Every model returns a ``Reply`` whose ``text`` is the model's raw output. The harness parses tool calls from that
text itself (plan section 12, row 12): the model writes ``<tool_call>`` blocks holding a JSON object with ``name``
and ``arguments``. A block that does not parse is kept as a malformed call and shown to the model as a tool
error, so it is counted and visible, never silently dropped.

``LlamaModel`` imports llama-cpp-python only when it is built, so the examples never need it. Replay reads the
stored replies and never runs a model; it refuses to answer when a request differs from the recorded one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .case import DATA

if TYPE_CHECKING:
    from .case import Task
    from .tools import ToolSet

RECORDED = DATA / "recorded"
MODEL_ALIAS = "qwen3-4b-instruct-2507"  # the name the recorded llama.cpp server is started with
BLOCK = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# The sampling the recordings used (recordings/local_model.py). The manifests record it; loopback_model sends the first two.
RECORDED_SAMPLING = {"temperature": 0, "top_k": 1, "seed": 4217}


@dataclass(frozen=True)
class Reply:
    """One model reply: the raw text, the parsed calls, the malformed blocks, and the token counts."""

    text: str
    tool_calls: list[dict] = field(default_factory=list)  # {"name": str, "arguments": dict}
    malformed: list[str] = field(default_factory=list)  # one short reason per block that did not parse
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"  # llama's "stop", or "length" when the token limit was reached


class ReplayMismatch(Exception):
    """The request differs from the recorded one, or the recording has no reply for this step."""


class Model(Protocol):
    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        """Return the model's reply to the messages, given the tool schemas."""
        ...


def parse_tool_calls(text: str) -> tuple[list[dict], list[str]]:
    """Read the ``<tool_call>`` blocks in a reply. Returns (valid calls, reasons for malformed blocks)."""
    calls, malformed = [], []
    for block in BLOCK.findall(text):
        try:
            obj = json.loads(block.strip())
        except json.JSONDecodeError as exc:
            malformed.append(f"not JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("name"), str):
            malformed.append("no tool name")
            continue
        arguments = obj.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                malformed.append("arguments are not JSON")
                continue
        if not isinstance(arguments, dict):
            malformed.append("arguments are not an object")
            continue
        calls.append({"name": obj["name"], "arguments": arguments})
    if text.count("<tool_call>") > len(BLOCK.findall(text)):
        malformed.append("unclosed tool call")
    return calls, malformed


def make_reply(text: str, prompt_tokens: int = 0, completion_tokens: int = 0, finish_reason: str = "stop") -> Reply:
    """Build a ``Reply`` from raw text, parsing its tool calls."""
    calls, malformed = parse_tool_calls(text)
    return Reply(text=text, tool_calls=calls, malformed=malformed, prompt_tokens=prompt_tokens,
                 completion_tokens=completion_tokens, finish_reason=finish_reason)


def request_hash(messages: list[dict], tools: list[dict]) -> str:
    """The sha256 of the request in canonical JSON. Replay compares this with the recorded hash."""
    text = json.dumps({"messages": messages, "tools": tools}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ScriptedModel:
    """Replies written by hand, in order. A string is raw text; a ``Reply`` is used as it is. Tokens are zero."""

    def __init__(self, replies: list[str | Reply]) -> None:
        self._replies = list(replies)
        self._next = 0

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        if self._next >= len(self._replies):
            raise IndexError("the scripted replies are used up")
        item = self._replies[self._next]
        self._next += 1
        return item if isinstance(item, Reply) else make_reply(item)


class ReplayModel:
    """The recorded replies of one run, in step order. Each request must hash to the recorded request."""

    def __init__(self, recording_name: str, run_key: str) -> None:
        path = RECORDED / recording_name / "replies.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self._rows = sorted((r for r in rows if r["run"] == run_key), key=lambda r: r["step"])
        self._next = 0

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        if self._next >= len(self._rows):
            raise ReplayMismatch(f"no recorded reply for step {self._next + 1}")
        row = self._rows[self._next]
        if request_hash(messages, tools) != row["request_sha256"]:
            raise ReplayMismatch(f"the request differs from the recorded one at step {row['step']}")
        self._next += 1
        # recordings made before finish_reason was kept have no such field: they were "stop" replies
        return make_reply(row["text"], row["prompt_tokens"], row["completion_tokens"],
                          row.get("finish_reason", "stop"))


class LoggedModel:
    """Wraps a live model and appends each raw reply to a JSON-lines file before the loop sees it.

    Used by the recordings. A run that stops midway leaves its replies in the file; the recording script drops
    them when it resumes (see ``recordings/task_set.py``).
    """

    def __init__(self, inner: Model, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._run_key = ""
        self._step = 0

    def begin(self, run_key: str) -> None:
        """Start a new run: its replies are numbered from step 1 under this key."""
        self._run_key, self._step = run_key, 0

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        reply = self._inner.reply(messages, tools)
        self._step += 1
        row = {"run": self._run_key, "step": self._step, "request_sha256": request_hash(messages, tools),
               "text": reply.text, "prompt_tokens": reply.prompt_tokens,
               "completion_tokens": reply.completion_tokens, "finish_reason": reply.finish_reason}
        with self._path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, sort_keys=True) + "\n")
            out.flush()
        return reply


class LlamaModel:
    """A live model through llama-cpp-python (pinned in ``recordings/requirements.txt``).

    Uses ``create_chat_completion`` with ``tools=``. At the pinned version the reply's ``content`` is the raw
    ``<tool_call>`` text and ``tool_calls`` is empty (plan section 12, row 12), so the harness parses the text.
    """

    def __init__(self, path: Path, *, n_ctx: int, n_threads: int, seed: int, max_tokens: int) -> None:
        from llama_cpp import Llama  # imported here only: examples never load it

        self._llm = Llama(model_path=str(path), n_ctx=n_ctx, n_threads=n_threads, seed=seed, verbose=False)
        self._max_tokens = max_tokens

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        out = self._llm.create_chat_completion(messages=messages, tools=tools, temperature=0, top_k=1,
                                               max_tokens=self._max_tokens)
        text = out["choices"][0]["message"].get("content") or ""
        usage = out["usage"]
        finish = out["choices"][0].get("finish_reason") or "stop"
        return make_reply(text, usage["prompt_tokens"], usage["completion_tokens"], finish)


def first_step(task: Task, tools: ToolSet) -> tuple[list[dict], list[dict]]:
    """The messages and tool schemas of a task's first step, built as ``lib/loop.py`` builds them."""
    return ([{"role": "system", "content": tools.system}, {"role": "user", "content": task.issue}],
            tools.schemas())


def parse_chat_body(body: str) -> Reply:
    """Read one chat-completions response body into a ``Reply``. The text is kept as the server sent it."""
    data = json.loads(body)
    choice = data["choices"][0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    usage = data.get("usage") or {}
    finish = choice.get("finish_reason") or "stop"
    structured = message.get("tool_calls") or []
    if not structured:
        calls, malformed = parse_tool_calls(text)
    else:
        calls, malformed = [], []
        for call in structured:
            function = call.get("function") or {}
            name, raw = function.get("name"), function.get("arguments", "")
            if not isinstance(name, str):
                malformed.append("no tool name")
                continue
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                malformed.append(f"arguments are not JSON ({exc.msg})")
                continue
            if not isinstance(arguments, dict):
                malformed.append("arguments are not an object")
                continue
            calls.append({"name": name, "arguments": arguments})
    return Reply(text=text, tool_calls=calls, malformed=malformed, prompt_tokens=usage.get("prompt_tokens", 0),
                 completion_tokens=usage.get("completion_tokens", 0), finish_reason=finish)


class UnsafeEndpoint(Exception):
    """The adapter refuses this endpoint: a redirect, a key over plain http to a remote host, or a non-http scheme."""


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Raises on every redirect, so no second request is sent and the key goes nowhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise UnsafeEndpoint(f"the endpoint answered {code} with a redirect, and the adapter does not follow redirects")


def _is_loopback(url: str) -> bool:
    return urllib.parse.urlsplit(url).hostname in LOOPBACK_HOSTS


class OpenAICompatibleModel:
    """A model behind an OpenAI-compatible ``/chat/completions`` endpoint, called with ``urllib`` and no SDK.

    ``request_body`` is the JSON the adapter sends. ``reply`` posts it and parses the response, keeping
    ``message.content`` as the text. Structured ``tool_calls`` are read here: each ``function.arguments`` string is
    parsed as JSON, and the tool's own model checks it when the loop runs the call. Without structured calls the
    ``<tool_call>`` blocks in the text are parsed, as for every other model. ``on_body`` gets each raw response body
    before it is parsed.

    Two rules are checked when the adapter is built, before any request: only ``http`` and ``https`` URLs are called,
    and an ``api_key`` is sent over ``https``, or over ``http`` only to a loopback host. A third applies to each request:
    a redirect is an error and is never followed. The environment's proxy settings are used, except for loopback hosts,
    which are reached directly.
    """

    def __init__(self, base_url: str, model: str, *, max_tokens: int, temperature: float = 0,
                 top_k: int | None = None, timeout: float = 600.0, api_key: str | None = None,
                 on_body: Callable[[str], None] | None = None) -> None:
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme not in ("http", "https"):
            raise UnsafeEndpoint(f"the scheme {parts.scheme!r} is not http or https")
        if api_key and parts.scheme == "http" and not _is_loopback(base_url):
            raise UnsafeEndpoint("the adapter sends an API key over https, or over http to a loopback host only")
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model, self._max_tokens, self._temperature, self._top_k = model, max_tokens, temperature, top_k
        self._timeout, self._api_key, self._on_body = timeout, api_key, on_body
        proxy = urllib.request.ProxyHandler({}) if _is_loopback(base_url) else urllib.request.ProxyHandler()
        self._opener = urllib.request.build_opener(proxy, _RefuseRedirects())

    def request_body(self, messages: list[dict], tools: list[dict]) -> dict:
        """The chat-completions body for one request. ``top_k`` is sent only when it is set."""
        body = {"model": self._model, "messages": messages, "tools": tools, "max_tokens": self._max_tokens,
                "temperature": self._temperature}
        if self._top_k is not None:
            body["top_k"] = self._top_k
        return body

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        data = json.dumps(self.request_body(messages, tools), sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(self._url, data=data, headers=headers, method="POST")
        with self._opener.open(request, timeout=self._timeout) as response:
            body = response.read().decode("utf-8")
        if self._on_body is not None:
            self._on_body(body)
        return parse_chat_body(body)


def loopback_model(base_url: str, on_body: Callable[[str], None] | None = None) -> OpenAICompatibleModel:
    """The adapter with the settings the recordings use: temperature 0, top_k 1, 1024 new tokens."""
    return OpenAICompatibleModel(base_url, MODEL_ALIAS, max_tokens=1024, temperature=RECORDED_SAMPLING["temperature"],
                                 top_k=RECORDED_SAMPLING["top_k"], on_body=on_body)


@contextmanager
def serve_recorded(name: str) -> Iterator[str]:
    """Serve a recording's exchanges from 127.0.0.1 on a port the OS picks, and yield the base URL.

    The stub answers requests in order with the recorded response bodies. A request that differs from the recorded
    one gets a 409, so the adapter raises rather than read a reply to another question. Until the recording exists,
    this raises ``FileNotFoundError``.
    """
    path = RECORDED / name / "exchanges.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"{name}: not recorded yet; run recordings/openai_compatible.py first")
    exchanges = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    pending = iter(exchanges)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            row = next(pending, None)
            if row is None or row["request"] != sent:
                self._send(409, b"the request differs from the recorded one")
            else:
                self._send(200, row["response"].encode("utf-8"))

        def _send(self, status: int, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:  # the stub stays quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        server.server_close()


_CHAT_BODY = '{"choices":[{"index":0,"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
_PROXY_VARS = ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")


def load_recording(name: str) -> tuple[dict, list[dict]]:
    """The manifest and the stored reply rows (``replies.jsonl``, in file order) of one recording."""
    folder = RECORDED / name
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (folder / "replies.jsonl").read_text(encoding="utf-8").splitlines()]
    return manifest, rows


class TextCapture:
    """Passes each reply through unchanged and keeps its text in ``texts``, so the texts can be compared with stored ones."""

    def __init__(self, inner: Model) -> None:
        self._inner, self.texts = inner, []

    def reply(self, messages: list[dict], tools: list[dict]) -> Reply:
        reply = self._inner.reply(messages, tools)
        self.texts.append(reply.text)
        return reply


def same_texts(rows: list[dict], texts: list[str]) -> int:
    """Assert that each text equals the stored text of the same reply, in order. Returns how many were compared."""
    compared = 0
    for stored, replayed in zip((row["text"] for row in rows), texts, strict=True):
        assert replayed == stored, f"reply {compared + 1} differs from its stored text"
        compared += 1
    return compared


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.seen.append(self.path)  # the path as the request line gave it; a proxy gets the absolute URL
        self.send_response(self.server.code)
        if 300 <= self.server.code < 400:
            self.send_header("Location", f"{self.server.url}/collect")
        payload = _CHAT_BODY.encode("utf-8")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # the stub stays quiet
        pass


@contextmanager
def stub_endpoint(code: int = 200) -> Iterator[HTTPServer]:
    """A loopback server on a port the OS picks, answering every POST with a valid chat reply and status ``code``.

    Each request path is appended to ``seen``. ``code`` can be changed between requests, and ``url`` is the server's
    base URL on 127.0.0.1. A 3xx status also sends a Location for ``/collect`` on the same server, so a followed
    redirect would show up in ``seen``.
    """
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    server.seen, server.code = [], code
    server.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def proxy_env(proxy: HTTPServer) -> Iterator[None]:
    """Route http requests through the stub ``proxy`` for the block only, with no bypass list, then restore the environment."""
    saved = {name: os.environ.get(name) for name in _PROXY_VARS}
    for name in _PROXY_VARS:
        os.environ.pop(name, None)
    os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = proxy.url
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def refusal(make: Callable[[], object]) -> str:
    """Run ``make``, which must raise UnsafeEndpoint, and return the reason it gives."""
    try:
        make()
    except UnsafeEndpoint as exc:
        return str(exc)
    raise AssertionError("the adapter did not refuse")


def stored_totals(manifest: dict, rows: list[dict]) -> tuple[int, int]:
    """The prompt and completion token totals of the stored reply rows. Asserts that they equal the manifest's totals."""
    prompt = sum(row["prompt_tokens"] for row in rows)
    completion = sum(row["completion_tokens"] for row in rows)
    assert prompt == manifest["prompt_tokens"] and completion == manifest["completion_tokens"], "the token totals differ"
    return prompt, completion
