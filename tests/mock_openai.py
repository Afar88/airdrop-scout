"""A scripted OpenAI-compatible /v1/chat/completions server for offline
integration tests. It is NOT a model: it replays a fixed plan
(list -> fetch first campaign -> final JSON) so we can prove the OpenMinion
wiring (config, tool registration, tool-call loop, typed output, errors,
timeouts) without an API key."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ScriptedLLM:
    def __init__(self, final_payload_fn, delay: float = 0.0, mode: str = "script",
                 first_tool: tuple[str, dict] | None = None):
        self.final_payload_fn = final_payload_fn
        self.delay = delay
        self.mode = mode  # script | bad_json | auth_error
        self.requests: list[dict] = []
        self.first_tool = first_tool
        self.internal_calls: list[str] = []

    def respond(self, body: dict) -> tuple[int, dict]:
        self.requests.append(body)
        if self.delay:
            time.sleep(self.delay)
        if self.mode == "auth_error":
            return 401, {"error": {"message": "Invalid API key", "type": "authentication_error", "code": "invalid_api_key"}}
        msgs = body.get("messages", [])
        forced = ((body.get("tool_choice") or {}) if isinstance(body.get("tool_choice"), dict) else {}).get("function", {}).get("name")
        if forced == "submit_output":
            # OpenMinion's internal structured phases (e.g. memory fact extraction)
            schema = (body.get("tools") or [{}])[0].get("function", {}).get("parameters", {})
            self.internal_calls.append(schema.get("title", "?"))
            return 200, _tool_call("submit_output", {"items": []} if "items" in schema.get("properties", {}) else {})
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        tool_names = {t.get("function", {}).get("name") for t in body.get("tools", []) or []}
        if not tool_msgs and self.first_tool and self.first_tool[0] in tool_names:
            return 200, _tool_call(*self.first_tool)
        if not tool_msgs and "list_recent_campaigns" in tool_names:
            return 200, _tool_call("list_recent_campaigns", {"days": 2})
        if len(tool_msgs) == 1 and "fetch_campaign_details" in tool_names:
            try:
                listing = unwrap_tool_content(tool_msgs[-1].get("content"))
                code = listing["campaigns"][0]["code"]
                return 200, _tool_call("fetch_campaign_details", {"url_or_code": code})
            except Exception:
                pass
        if self.mode == "bad_json":
            return 200, _text("Sure! Here are some campaigns, but no JSON.")
        return 200, _text(json.dumps(self.final_payload_fn(msgs)))


def unwrap_tool_content(content) -> dict:
    """OpenMinion wraps tool results as {"status","summary","outputs": ...}.
    A str return arrives as outputs={"data": <str>}; a dict return is outputs itself."""
    obj = json.loads(content or "{}")
    outputs = obj.get("outputs", obj) if isinstance(obj, dict) else obj
    data = outputs.get("data", outputs) if isinstance(outputs, dict) else outputs
    return json.loads(data) if isinstance(data, str) else data


def _envelope(message: dict, finish: str) -> dict:
    return {
        "id": "chatcmpl-mock", "object": "chat.completion", "created": int(time.time()),
        "model": "mock-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


_n = 0


def _tool_call(name: str, args: dict) -> dict:
    global _n
    _n += 1
    return _envelope({"role": "assistant", "content": None, "tool_calls": [{
        "id": f"call_{_n}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls")


def _text(content: str) -> dict:
    return _envelope({"role": "assistant", "content": content}, "stop")


def serve(llm: ScriptedLLM) -> tuple[ThreadingHTTPServer, str]:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if body.get("stream"):
                status, payload = 400, {"error": {"message": "mock does not stream"}}
            else:
                status, payload = llm.respond(body)
            data = json.dumps(payload).encode()
            try:
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            data = json.dumps({"data": [{"id": "mock-model"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"
