import os

from airdrop_scout.__main__ import load_dotenv, main


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# c\nSCOUT_X1='a'\nexport SCOUT_X2=b\nSCOUT_X3=\nSCOUT_X4=keep\n")
    monkeypatch.setenv("SCOUT_X4", "real")
    for k in ("SCOUT_X1", "SCOUT_X2", "SCOUT_X3"):
        monkeypatch.delenv(k, raising=False)
    load_dotenv(env)
    assert os.environ["SCOUT_X1"] == "a" and os.environ["SCOUT_X2"] == "b"
    assert "SCOUT_X3" not in os.environ and os.environ["SCOUT_X4"] == "real"
    for k in ("SCOUT_X1", "SCOUT_X2"):
        monkeypatch.delenv(k)


def test_cli_without_key_exits_1(tmp_path, monkeypatch, capsys):
    for k in ("SCOUT_PROVIDER", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "CORTENSOR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENMINION_HOME", str(tmp_path))
    monkeypatch.setenv("OPENMINION_DATA_ROOT", str(tmp_path / ".openminion"))
    assert main(["--env-file", str(tmp_path / "none"), "--out", str(tmp_path)]) == 1
    monkeypatch.setenv("SCOUT_PROVIDER", "cortensor-portal")
    assert main(["--env-file", str(tmp_path / "none"), "--out", str(tmp_path)]) == 1
    assert "CORTENSOR_API_KEY is not set" in capsys.readouterr().err
