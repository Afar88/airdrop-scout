"""Self-contained offline harness for verifying an installed openminion package.

A tiny scripted OpenAI-compatible /v1/chat/completions server (not a model):
on the first request that offers `tool_name` it returns one tool call with
`tool_args`; every other request gets a short final text answer (or `{}` for
OpenMinion's internal forced `submit_output` phases). Optional `delay` seconds
before each answer, to exercise timeout and cancellation.

`make_env()` writes an isolated OpenMinion config (temporary OPENMINION_HOME
and data root) pointing at that server. No API key or network needed.
Standard library only; works with any openminion >= 0.1.10.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Script:
    def __init__(self, tool_name: str | None = None, tool_args: dict | None = None,
                 delay: float = 0.0, final_text: str = "FINAL_OK"):
        self.tool_name, self.tool_args = tool_name, tool_args or {}
        self.delay, self.final_text = delay, final_text
        self.requests: list[dict] = []
        self.tool_sent = False
        self._lock = threading.Lock()

    def respond(self, body: dict) -> dict:
        with self._lock:
            self.requests.append(body)
        if self.delay:
            time.sleep(self.delay)
        tc = body.get("tool_choice")
        forced = tc.get("function", {}).get("name") if isinstance(tc, dict) else None
        if forced == "submit_output":
            schema = (body.get("tools") or [{}])[0].get("function", {}).get("parameters", {})
            args = {"items": []} if "items" in schema.get("properties", {}) else {}
            return _call("submit_output", args)
        names = {t.get("function", {}).get("name") for t in body.get("tools") or []}
        with self._lock:
            send = self.tool_name in names and not self.tool_sent
            if send:
                self.tool_sent = True
        if send:
            return _call(self.tool_name, self.tool_args)
        return _env({"role": "assistant", "content": self.final_text}, "stop")

    def tool_messages(self) -> list[dict]:
        out = []
        for q in self.requests:
            for m in q.get("messages", []):
                if m.get("role") == "tool" and m not in out:
                    out.append(m)
        return out


_n = 0


def _call(name: str, args: dict) -> dict:
    global _n
    _n += 1
    return _env({"role": "assistant", "content": None, "tool_calls": [{
        "id": f"call_{_n}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls")


def _env(message: dict, finish: str) -> dict:
    return {"id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
            "model": "mock-model",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}


def serve(script: Script):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status: int, payload: dict):
            data = json.dumps(payload).encode()
            try:
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if body.get("stream"):
                return self._send(400, {"error": {"message": "mock does not stream"}})
            self._send(200, script.respond(body))

        def do_GET(self):
            self._send(200, {"data": [{"id": "mock-model"}]})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def make_env(script: Script):
    """Start the server and write an isolated config. Returns (server, config_path)."""
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    home = tempfile.mkdtemp(prefix="om-verify-")
    os.environ["OPENMINION_HOME"] = home
    os.environ["OPENMINION_DATA_ROOT"] = os.path.join(home, ".openminion")
    os.environ["MOCK_KEY"] = "mock"
    srv, url = serve(script)
    cfg = {
        "default_agent": "a",
        "agents": {"a": {"name": "a", "provider": "openai", "default_channel": "console"}},
        "providers": {"openai": {"model": "mock-model", "base_url": url, "api_key_env": "MOCK_KEY"}},
        "runtime": {"memory_enabled": False},
    }
    path = os.path.join(home, "agents.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return srv, path
