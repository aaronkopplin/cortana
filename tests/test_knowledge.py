import os
import json
import sys
import types
import tempfile
import asyncio

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Ensure cli imports without real openai dependency
fake_openai = types.SimpleNamespace()
sys.modules.setdefault("openai", fake_openai)

import cortana as cli


def test_load_knowledge_initializes_file(monkeypatch, tmp_path):
    path = tmp_path / "kb.json"
    monkeypatch.setattr(cli, "gather_system_info", lambda: {"os": "FakeOS"})
    data = cli.load_knowledge(str(path))
    assert path.exists()
    assert data["system"]["os"] == "FakeOS"
    assert data["commands"] == []
    with open(path) as f:
        saved = json.load(f)
    assert saved == data


def test_load_knowledge_handles_invalid_json(monkeypatch, tmp_path):
    path = tmp_path / "kb.json"
    path.write_text("{broken")
    monkeypatch.setattr(cli, "gather_system_info", lambda: {"os": "FakeOS"})
    data = cli.load_knowledge(str(path))
    assert data["system"]["os"] == "FakeOS"
    assert data["commands"] == []


def test_update_knowledge_appends_command(tmp_path, monkeypatch):
    path = tmp_path / "kb.json"
    monkeypatch.setattr(cli, "gather_system_info", lambda: {"os": "FakeOS"})
    data = cli.load_knowledge(str(path))
    cli.update_knowledge(str(path), data, "echo hi", "hi\n", True)
    with open(path) as f:
        saved = json.load(f)
    assert saved["commands"][-1] == {
        "command": "echo hi",
        "output": "hi\n",
        "success": True,
    }


def test_run_command_success_and_failure():
    out, success = cli.run_command("echo test")
    assert success
    assert out.strip() == "test"
    out2, success2 = cli.run_command("false")
    assert not success2


def test_run_command_async_success_and_failure():
    out, success = asyncio.run(cli.run_command_async("echo async"))
    assert success
    assert out.strip() == "async"
    out2, success2 = asyncio.run(cli.run_command_async("false"))
    assert not success2


def test_check_command_rules():
    rules = {"blocked": [], "confirm": ["apt install"]}
    assert cli.check_command_rules("rm file", {"blocked": ["rm"], "confirm": []}) == "block"
    assert cli.check_command_rules("sudo apt install htop", rules) == "confirm"
    assert cli.check_command_rules("rm -rf /", rules) == "danger"
    assert cli.check_command_rules("nano file.txt", rules) == "block"
    assert cli.check_command_rules("vim file.txt", rules) == "block"


def test_persistent_cd(monkeypatch, tmp_path):
    cli.CURRENT_DIR = str(tmp_path)
    out, success = cli.run_command("pwd")
    assert success
    assert out.strip() == str(tmp_path)
    cli.run_command("mkdir sub")
    cli.run_command("cd sub")
    out2, success2 = cli.run_command("pwd")
    assert success2
    assert out2.strip() == str(tmp_path / "sub")


def test_edit_file(monkeypatch, tmp_path):
    cli.CURRENT_DIR = str(tmp_path)
    out, success = cli.run_command("edit file.txt hello")
    assert success
    assert (tmp_path / "file.txt").read_text() == "hello"


def test_load_knowledge_includes_stats(monkeypatch, tmp_path):
    path = tmp_path / "kb.json"
    monkeypatch.setattr(cli, "gather_system_info", lambda: {"os": "Fake"})
    data = cli.load_knowledge(str(path))
    assert "stats" in data


def test_update_knowledge_stats(monkeypatch, tmp_path):
    path = tmp_path / "kb.json"
    monkeypatch.setattr(cli, "gather_system_info", lambda: {"os": "Fake"})
    data = cli.load_knowledge(str(path))
    cli.update_knowledge(str(path), data, "cmd", "", True)
    cli.update_knowledge(str(path), data, "cmd", "", False)
    with open(path) as f:
        saved = json.load(f)
    assert saved["stats"]["cmd"]["success"] == 1
    assert saved["stats"]["cmd"]["failure"] == 1


def test_run_command_failure_message(capsys):
    cli.run_command("false")
    captured = capsys.readouterr().out
    assert "Command exited with code" in captured
