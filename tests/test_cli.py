import builtins
import io
import os
import sys
import types
import tempfile
import json
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Fake openai module so cli can import
class FakeOpenAIClient:
    def __init__(self, create_fn=None):
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=create_fn)
        )


fake_openai = types.SimpleNamespace(OpenAI=lambda **_: FakeOpenAIClient())
sys.modules["openai"] = fake_openai

import cortana as cli


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [types.SimpleNamespace(message={"content": content})]


def run_cli_single_question(
    monkeypatch, question: str, replies, knowledge_file: str, extra_inputs=None
) -> str:
    if isinstance(replies, str):
        replies = [replies]
    inputs_list = [question]
    if extra_inputs:
        inputs_list.extend(extra_inputs)
    else:
        inputs_list.append("n")
    out, _ = run_cli_inputs(monkeypatch, inputs_list, replies, knowledge_file)
    return out


def run_cli_inputs(monkeypatch, inputs, replies, knowledge_file):
    input_iter = iter(inputs + ["exit"])

    def fake_input(prompt=""):
        print(prompt, end="")
        return next(input_iter)

    replies_iter = iter(replies)
    calls = []

    def fake_create(**_kwargs):
        calls.append([m.copy() for m in _kwargs.get("messages", [])])
        return FakeResponse(next(replies_iter))

    monkeypatch.setattr(builtins, "input", fake_input)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("CORTANA_KNOWLEDGE_FILE", knowledge_file)
    monkeypatch.setattr(
        cli.openai,
        "OpenAI",
        lambda **_: FakeOpenAIClient(fake_create),
        raising=False,
    )
    output = io.StringIO()
    with patch("sys.stdout", output):
        cli.main()
    return output.getvalue(), calls


def extract_command(text: str) -> str | None:
    for line in text.splitlines():
        if line.lower().startswith("command:"):
            return line.split(":", 1)[1].strip()
    return None


def assert_command_response(
    monkeypatch, question: str, reply: str, valid_commands=None
):
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        path = tmp.name
    out = run_cli_single_question(monkeypatch, question, reply, path)
    with open(path) as f:
        data = json.load(f)
    assert "system" in data
    assert "commands" in data
    assert "AI:" in out
    response_text = out.split("AI:", 1)[1].strip()
    cmd = extract_command(response_text)
    assert cmd, "response should include a command suggestion"
    if valid_commands is not None:
        assert cmd in valid_commands
    explanation = response_text.split("Command:", 1)[0].strip()
    assert explanation, "response should include an explanation"


@pytest.mark.parametrize(
    "question,reply,commands",
    [
        (
            "cortana how do I list out all the files in the current directory",
            '{"explanation": "To list all files and directories in the current directory, use the ls command.", "command": "ls"}',
            ["ls"],
        ),
        (
            "cortana how do I list all the files in my Documents folder",
            '{"explanation": "List files in a specific directory by providing a path.", "command": "ls ~/Documents"}',
            ["ls ~/Documents", "ls"],
        ),
        (
            "cortana how do I navigate to my home directory",
            '{"explanation": "Use cd to change directories.", "command": "cd ~"}',
            ["cd ~", "cd"],
        ),
        (
            "cortana how do I make a new folder called projects",
            '{"explanation": "Use mkdir to create directories.", "command": "mkdir projects"}',
            ["mkdir projects"],
        ),
        (
            "cortana how do I create an empty text file named notes.txt",
            '{"explanation": "Create empty files with touch.", "command": "touch notes.txt"}',
            ["touch notes.txt"],
        ),
        (
            "cortana how do I copy a file named document.pdf to my backup folder",
            '{"explanation": "Copy files using cp.", "command": "cp document.pdf ~/backup"}',
            ["cp document.pdf ~/backup"],
        ),
        (
            "cortana how do I move a file from my downloads to my desktop",
            '{"explanation": "Move files with mv.", "command": "mv ~/Downloads/myfile.zip ~/Desktop"}',
            ["mv ~/Downloads/myfile.zip ~/Desktop"],
        ),
        (
            "cortana how do I delete a file called temp.log",
            '{"explanation": "Remove files using rm.", "command": "rm temp.log"}',
            ["rm temp.log"],
        ),
        (
            "cortana how do I check my disk space",
            '{"explanation": "Check disk usage with df.", "command": "df -h"}',
            ["df -h", "df"],
        ),
        (
            "cortana how much memory is my computer using",
            '{"explanation": "Check memory usage with free.", "command": "free -h"}',
            ["free -h", "free"],
        ),
        (
            "cortana how do I see what programs are running",
            '{"explanation": "List running processes with ps.", "command": "ps aux"}',
            ["ps aux", "ps"],
        ),
        (
            "cortana what's my IP address",
            '{"explanation": "Network information can be retrieved with ip.", "command": "ip a"}',
            ["ip a", "ip"],
        ),
        (
            "cortana how do I ping google.com",
            '{"explanation": "Use ping to test connectivity. Stop with Ctrl+C.", "command": "ping google.com"}',
            ["ping google.com", "ping"],
        ),
        (
            "cortana how do I update my package list",
            '{"explanation": "Update packages with apt.", "command": "sudo apt update"}',
            ["sudo apt update"],
        ),
        (
            "cortana how do I install a new program called htop",
            '{"explanation": "Install packages with apt.", "command": "sudo apt install htop"}',
            ["sudo apt install htop"],
        ),
    ],
)
def test_command_responses(monkeypatch, question, reply, commands):
    assert_command_response(monkeypatch, question, reply, commands)


def test_very_long_prompt(monkeypatch):
    question = "cortana I need to find a very specific file that I downloaded last week and I think it was called something like report_final_v2_draft.docx but I'm not entirely sure and I need to move it to a different directory after I find it and then maybe I need to rename it to something simpler like final_report.docx and also I want to make a backup of it before I do anything else with it so please tell me all the commands for that because I am very confused about it all and this is a very long question."
    reply = '{"explanation": "That\'s a multi-step task. First, search for the file with find.", "command": "find ~/Downloads -name \'report_final_v2_draft.docx\'"}'
    assert_command_response(
        monkeypatch,
        question,
        reply,
        ["find ~/Downloads -name 'report_final_v2_draft.docx'", "find"],
    )


def test_blocked_command(monkeypatch, tmp_path):
    safety = tmp_path / "safety.yaml"
    safety.write_text("blocked:\n  - rm ")
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    knowledge = tmp_path / "know.json"
    out = run_cli_single_question(
        monkeypatch,
        "delete file",
        '{"explanation": "Remove file", "command": "rm temp.log"}',
        str(knowledge),
        extra_inputs=[],
    )
    assert "Command blocked by safety rules" in out


def test_confirm_command(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("confirm:\n  - apt install")
    safety = tmp_path / "safety.yaml"
    safety.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    knowledge = tmp_path / "know.json"
    out = run_cli_single_question(
        monkeypatch,
        "install package",
        '{"explanation": "Install", "command": "sudo apt install htop"}',
        str(knowledge),
        extra_inputs=["yes", "n"],
    )
    assert "requires extra confirmation" in out


def test_command_execution_records_success(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    safety = tmp_path / "safety.yaml"
    safety.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    knowledge = tmp_path / "know.json"

    monkeypatch.setattr(cli, "run_command", lambda cmd: ("hi\n", True))

    out = run_cli_single_question(
        monkeypatch,
        "run it",
        [
            '{"explanation": "test", "command": "echo hi"}',
            '{"explanation": "done", "command": ""}',
        ],
        str(knowledge),
        extra_inputs=[""],
    )

    with open(knowledge) as f:
        data = json.load(f)

    assert data["commands"][-1]["success"] is True

    # Cortana should automatically provide feedback after executing the command
    assert "AI: done" in out


def test_dangerous_command_requires_warning(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    safety = tmp_path / "safety.yaml"
    safety.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    knowledge = tmp_path / "know.json"

    monkeypatch.setattr(cli, "run_command", lambda cmd: ("", True))

    out = run_cli_single_question(
        monkeypatch,
        "danger",
        '{"explanation": "oops", "command": "rm -rf /"}',
        str(knowledge),
        extra_inputs=["yes", "n"],
    )

    assert "Dangerous command detected" in out


def test_dangerous_command_blocked(monkeypatch, tmp_path):
    safety = tmp_path / "safety.yaml"
    safety.write_text("blocked:\n  - rm -rf")
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    knowledge = tmp_path / "know.json"

    out = run_cli_single_question(
        monkeypatch,
        "danger",
        '{"explanation": "oops", "command": "rm -rf /"}',
        str(knowledge),
        extra_inputs=[],
    )

    assert "Command blocked by safety rules" in out
    assert "Dangerous command detected" not in out


def test_auto_approve(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    safety = tmp_path / "safety.yaml"
    safety.write_text("")
    whitelist = tmp_path / ".cortanaignore"
    whitelist.write_text("ls\n")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    monkeypatch.setenv("CORTANA_WHITELIST", str(whitelist))
    monkeypatch.setattr(cli, "run_command", lambda cmd: ("", True))
    knowledge = tmp_path / "kb.json"
    out, _ = run_cli_inputs(
        monkeypatch,
        ["show"],
        [
            '{"explanation": "list", "command": "ls /"}',
            '{"explanation": "done", "command": ""}',
        ],
        str(knowledge),
    )
    assert "Running: ls /" in out
    assert "Execute?" not in out


def test_default_whitelist(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.yaml"
    prefs.write_text("")
    safety = tmp_path / "safety.yaml"
    safety.write_text("")
    monkeypatch.setenv("CORTANA_SAFETY_RULES", str(safety))
    monkeypatch.setenv("CORTANA_PREFERENCES", str(prefs))
    monkeypatch.delenv("CORTANA_WHITELIST", raising=False)
    monkeypatch.setattr(cli, "run_command", lambda cmd: ("", True))
    knowledge = tmp_path / "kb.json"
    out, _ = run_cli_inputs(
        monkeypatch,
        ["show"],
        [
            '{"explanation": "list", "command": "ls /"}',
            '{"explanation": "done", "command": ""}',
        ],
        str(knowledge),
    )
    assert "Running: ls /" in out
    assert "Execute?" not in out


def test_invalid_json_response(monkeypatch, tmp_path):
    knowledge = tmp_path / "kb.json"
    out = run_cli_single_question(
        monkeypatch,
        "hello",
        "not-json",
        str(knowledge),
        extra_inputs=[],
    )
    assert "Invalid JSON response from AI." in out
    assert "rephrasing" in out
    assert "not-json" in out
    with open(knowledge) as f:
        data = json.load(f)
    assert data["commands"] == []


def test_unescaped_quotes(monkeypatch, tmp_path):
    knowledge = tmp_path / "kb.json"
    reply = '{"explanation": "He said "hello"", "command": "echo "hi""}'
    out = run_cli_single_question(
        monkeypatch,
        "quote",
        reply,
        str(knowledge),
        extra_inputs=[],
    )
    assert 'He said "hello"' in out
    assert 'Command: echo "hi"' in out


def test_new_conversation_command(monkeypatch, tmp_path):
    knowledge = tmp_path / "kb.json"
    replies = [
        '{"explanation": "hi", "command": ""}',
        '{"explanation": "again", "command": ""}',
    ]
    out, calls = run_cli_inputs(
        monkeypatch,
        ["hello", "new", "hello"],
        replies,
        str(knowledge),
    )
    assert "Starting a new conversation." in out
    assert len(calls) == 2
    assert len(calls[1]) == 2  # system + user only
