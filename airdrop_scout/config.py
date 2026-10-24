"""Provider-agnostic OpenMinion config, generated from environment variables.

We write a project-local agents.json and hand it to `Agent(config_path=...)`,
so the user's ~/.openminion config is never touched. The provider blocks below
mirror what `openminion setup --provider <id> --model <model> --no-chat`
writes in openminion 0.1.10 (checked by running setup in an isolated
OPENMINION_HOME), trimmed to the documented fields: provider, model,
api_key_env, base_url, timeout_seconds.

Env:
  SCOUT_PROVIDER   openrouter | openai | ollama | cortensor-portal | echo
                   (default: first one whose key is present, else echo)
  SCOUT_MODEL      model id override (defaults below match the setup presets)
  OPENROUTER_API_KEY / OPENAI_API_KEY / CORTENSOR_API_KEY
  OLLAMA_BASE_URL  default http://127.0.0.1:11434
  SCOUT_BASE_URL   optional endpoint override (any OpenAI-compatible URL; used by tests)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

AGENT_ID = "scout"

PRESETS: dict[str, dict] = {
    "openrouter": {
        "provider": "openrouter",
        "model": "openai/gpt-4.1-mini",
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "timeout_seconds": 120,
    },
    "openai": {
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "timeout_seconds": 120,
    },
    "ollama": {
        "provider": "ollama",
        "model": "llama3.1",
        "key_env": None,
        "base_url": "http://127.0.0.1:11434",
        "timeout_seconds": 300,
    },
    # Cortensor Portal is OpenAI-compatible: setup maps it onto the `openai`
    # provider block with Cortensor's base URL, CORTENSOR_API_KEY and a long
    # request timeout (480 s in 0.1.10).
    "cortensor-portal": {
        "provider": "openai",
        "model": "oss-20b",
        "key_env": "CORTENSOR_API_KEY",
        "base_url": "https://api.cortensor.app/v1",
        "timeout_seconds": 480,
        "provider_identity": {
            "model_family": "oss",
            "service_vendor": "cortensor",
            "transport_adapter": "openai_chat",
            "wire_protocol_family": "openai_chat_completions",
        },
    },
    "echo": {"provider": "echo", "model": "echo", "key_env": None},
}

AUTO_ORDER = ["cortensor-portal", "openrouter", "openai"]


@dataclass(frozen=True)
class ProviderChoice:
    preset: str
    provider: str
    model: str
    key_env: str | None

    @property
    def has_key(self) -> bool:
        return self.key_env is None or bool(os.environ.get(self.key_env))


def choose_provider(env: dict[str, str] | None = None) -> ProviderChoice:
    env = dict(os.environ if env is None else env)
    name = (env.get("SCOUT_PROVIDER") or "").strip().lower()
    if not name:
        name = next((p for p in AUTO_ORDER if env.get(PRESETS[p]["key_env"])), "echo")
    if name == "cortensor":
        name = "cortensor-portal"
    if name not in PRESETS:
        raise ValueError(f"SCOUT_PROVIDER={name!r} not supported; pick one of {sorted(PRESETS)}")
    p = PRESETS[name]
    return ProviderChoice(name, p["provider"], (env.get("SCOUT_MODEL") or p["model"]).strip(), p["key_env"])


def build_config(choice: ProviderChoice, env: dict[str, str] | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    p = PRESETS[choice.preset]
    agent = {
        "name": AGENT_ID,
        "provider": p["provider"],
        # Required in 0.1.10: without a channel the gateway rejects the turn
        # with "inbound authenticity denied (reason=invalid_channel)".
        "default_channel": "console",
    }
    cfg: dict = {"default_agent": AGENT_ID, "agents": {AGENT_ID: agent}}
    # The scout keeps its own seen-store; OpenMinion long-term memory would add
    # an extra fact-extraction LLM call per turn (slow on Cortensor Portal).
    # Set SCOUT_OPENMINION_MEMORY=1 to turn it back on.
    runtime: dict = {"log_level": env.get("SCOUT_LOG_LEVEL", "WARNING")}
    if env.get("SCOUT_OPENMINION_MEMORY", "0") not in ("1", "true", "yes"):
        runtime["memory_enabled"] = False
    cfg["runtime"] = runtime
    if p["provider"] == "echo":
        return cfg
    block: dict = {"model": choice.model, "timeout_seconds": p["timeout_seconds"]}
    base_url = p["base_url"]
    if choice.preset == "ollama":
        base_url = env.get("OLLAMA_BASE_URL") or base_url
    base_url = (env.get("SCOUT_BASE_URL") or base_url).rstrip("/")
    block["base_url"] = base_url
    if p["key_env"]:
        block["api_key_env"] = p["key_env"]
    if p.get("provider_identity"):
        block["provider_identity"] = dict(p["provider_identity"])
    cfg["providers"] = {p["provider"]: block}
    return cfg


def write_config(choice: ProviderChoice, directory: Path | str) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "agents.json"
    path.write_text(json.dumps(build_config(choice), indent=2) + "\n")
    return path


def isolate_openminion_home(project_dir: Path | str) -> Path:
    """Point OpenMinion state at <project>/.openminion (documented env vars)."""
    home = Path(project_dir).resolve()
    os.environ.setdefault("OPENMINION_HOME", str(home))
    os.environ.setdefault("OPENMINION_DATA_ROOT", str(home / ".openminion"))
    return Path(os.environ["OPENMINION_DATA_ROOT"])
