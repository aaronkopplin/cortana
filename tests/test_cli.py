import builtins
import io
import os
import sys
import types
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Fake openai module so cli can import
fake_openai = types.SimpleNamespace(ChatCompletion=types.SimpleNamespace())
sys.modules['openai'] = fake_openai

import cli


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [types.SimpleNamespace(message={"content": content})]


def run_cli_single_question(monkeypatch, question: str, reply: str) -> str:
    inputs = iter([question, "exit"])
    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    def fake_create(**_kwargs):
        return FakeResponse(reply)

    monkeypatch.setattr(cli.openai.ChatCompletion, "create", fake_create, raising=False)
    output = io.StringIO()
    with patch("sys.stdout", output):
        cli.main()
    return output.getvalue()


def extract_command(text: str) -> str | None:
    for line in text.splitlines():
        if line.lower().startswith("command:"):
            return line.split(":", 1)[1].strip()
    return None


def assert_command_response(monkeypatch, question: str, reply: str, valid_commands=None):
    out = run_cli_single_question(monkeypatch, question, reply)
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
            "To list all files and directories in the current directory, use the ls command.\nCommand: ls",
            ["ls"],
        ),
        (
            "cortana how do I list all the files in my Documents folder",
            "List files in a specific directory by providing a path.\nCommand: ls ~/Documents",
            ["ls ~/Documents", "ls"],
        ),
        (
            "cortana how do I navigate to my home directory",
            "Use cd to change directories.\nCommand: cd ~",
            ["cd ~", "cd"],
        ),
        (
            "cortana how do I make a new folder called projects",
            "Use mkdir to create directories.\nCommand: mkdir projects",
            ["mkdir projects"],
        ),
        (
            "cortana how do I create an empty text file named notes.txt",
            "Create empty files with touch.\nCommand: touch notes.txt",
            ["touch notes.txt"],
        ),
        (
            "cortana how do I copy a file named document.pdf to my backup folder",
            "Copy files using cp.\nCommand: cp document.pdf ~/backup",
            ["cp document.pdf ~/backup"],
        ),
        (
            "cortana how do I move a file from my downloads to my desktop",
            "Move files with mv.\nCommand: mv ~/Downloads/myfile.zip ~/Desktop",
            ["mv ~/Downloads/myfile.zip ~/Desktop"],
        ),
        (
            "cortana how do I delete a file called temp.log",
            "Remove files using rm.\nCommand: rm temp.log",
            ["rm temp.log"],
        ),
        (
            "cortana how do I check my disk space",
            "Check disk usage with df.\nCommand: df -h",
            ["df -h", "df"],
        ),
        (
            "cortana how much memory is my computer using",
            "Check memory usage with free.\nCommand: free -h",
            ["free -h", "free"],
        ),
        (
            "cortana how do I see what programs are running",
            "List running processes with ps.\nCommand: ps aux",
            ["ps aux", "ps"],
        ),
        (
            "cortana what's my IP address",
            "Network information can be retrieved with ip.\nCommand: ip a",
            ["ip a", "ip"],
        ),
        (
            "cortana how do I ping google.com",
            "Use ping to test connectivity. Stop with Ctrl+C.\nCommand: ping google.com",
            ["ping google.com", "ping"],
        ),
        (
            "cortana how do I update my package list",
            "Update packages with apt.\nCommand: sudo apt update",
            ["sudo apt update"],
        ),
        (
            "cortana how do I install a new program called htop",
            "Install packages with apt.\nCommand: sudo apt install htop",
            ["sudo apt install htop"],
        ),
    ],
)
def test_command_responses(monkeypatch, question, reply, commands):
    assert_command_response(monkeypatch, question, reply, commands)


def test_very_long_prompt(monkeypatch):
    question = (
        "cortana I need to find a very specific file that I downloaded last week and I think it was called something like report_final_v2_draft.docx but I'm not entirely sure and I need to move it to a different directory after I find it and then maybe I need to rename it to something simpler like final_report.docx and also I want to make a backup of it before I do anything else with it so please tell me all the commands for that because I am very confused about it all and this is a very long question."
    )
    reply = (
        "That's a multi-step task. First, search for the file with find.\nCommand: find ~/Downloads -name 'report_final_v2_draft.docx'"
    )
    assert_command_response(monkeypatch, question, reply, ["find ~/Downloads -name 'report_final_v2_draft.docx'", "find"])
