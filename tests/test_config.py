import json

import pytest

from airdrop_scout.config import PRESETS, build_config, choose_provider, write_config


def test_auto_choice_order():
    assert choose_provider({}).preset == "echo"
    assert choose_provider({"OPENAI_API_KEY": "x"}).preset == "openai"
    assert choose_provider({"OPENAI_API_KEY": "x", "OPENROUTER_API_KEY": "y"}).preset == "openrouter"
    assert choose_provider({"OPENROUTER_API_KEY": "y", "CORTENSOR_API_KEY": "z"}).preset == "cortensor-portal"


def test_explicit_choice_alias_and_model_override():
    c = choose_provider({"SCOUT_PROVIDER": "cortensor"})
    assert (c.preset, c.provider, c.model, c.key_env) == ("cortensor-portal", "openai", "oss-20b", "CORTENSOR_API_KEY")
    assert choose_provider({"SCOUT_PROVIDER": "openrouter", "SCOUT_MODEL": "x/y"}).model == "x/y"
    with pytest.raises(ValueError):
        choose_provider({"SCOUT_PROVIDER": "nope"})


@pytest.mark.parametrize("preset", ["openrouter", "openai", "ollama", "cortensor-portal"])
def test_build_config_shapes(preset):
    cfg = build_config(choose_provider({"SCOUT_PROVIDER": preset}), env={})
    agent = cfg["agents"]["scout"]
    assert cfg["default_agent"] == "scout"
    assert agent["default_channel"] == "console"
    block = cfg["providers"][agent["provider"]]
    assert block["model"] == PRESETS[preset]["model"]
    assert block["base_url"] == PRESETS[preset]["base_url"]
    assert ("api_key_env" in block) == (PRESETS[preset]["key_env"] is not None)
    assert "api_key" not in block  # never write secrets
    assert cfg["runtime"] == {"log_level": "WARNING", "memory_enabled": False}


def test_cortensor_portal_matches_setup_preset():
    cfg = build_config(choose_provider({"SCOUT_PROVIDER": "cortensor-portal"}), env={})
    block = cfg["providers"]["openai"]
    assert block["base_url"] == "https://api.cortensor.app/v1"
    assert block["api_key_env"] == "CORTENSOR_API_KEY"
    assert block["timeout_seconds"] == 480


def test_env_overrides():
    env = {"SCOUT_PROVIDER": "ollama", "OLLAMA_BASE_URL": "http://gpu:11434/", "SCOUT_OPENMINION_MEMORY": "1"}
    cfg = build_config(choose_provider(env), env=env)
    assert cfg["providers"]["ollama"]["base_url"] == "http://gpu:11434"
    assert "memory_enabled" not in cfg["runtime"]


@pytest.mark.parametrize("preset", ["echo", "openrouter", "cortensor-portal"])
def test_generated_config_loads_in_openminion(preset, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMINION_HOME", str(tmp_path))
    monkeypatch.setenv("OPENMINION_DATA_ROOT", str(tmp_path / ".openminion"))
    # APIRuntime builds the provider eagerly and raises ProviderError when the
    # key env var is empty, so give it a placeholder (no request is made).
    monkeypatch.setenv("OPENROUTER_API_KEY", "placeholder")
    monkeypatch.setenv("CORTENSOR_API_KEY", "placeholder")
    from openminion import APIRuntime
    path = write_config(choose_provider({"SCOUT_PROVIDER": preset}), tmp_path / ".openminion")
    json.loads(path.read_text())
    runtime = APIRuntime.from_config_path(str(path))
    runtime.close()
    runtime.close()  # documented as safe to repeat
