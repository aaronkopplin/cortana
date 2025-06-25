import json
import sys
import types
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

fake_openai = types.SimpleNamespace(ChatCompletion=types.SimpleNamespace())
sys.modules.setdefault("openai", fake_openai)

import cli
import planner


def test_execute_plan_success(monkeypatch, tmp_path):
    knowledge_path = tmp_path / "kb.json"
    planner.save_plan(str(tmp_path / "plan.json"), [planner.PlanStep(description="step", command="echo hi")])
    monkeypatch.setattr(cli, "run_command", lambda cmd: ("hi\n", True))
    monkeypatch.setattr(cli, "update_knowledge", lambda *a, **k: None)
    knowledge = {"system": {}, "commands": []}
    steps = planner.load_plan(str(tmp_path / "plan.json"))
    planner.execute_plan(steps, str(tmp_path / "plan.json"), knowledge, str(knowledge_path), cli.run_command, cli.update_knowledge)
    assert steps[0].status == "done"


def test_execute_plan_failure(monkeypatch, tmp_path):
    plan_file = tmp_path / "plan.json"
    planner.save_plan(str(plan_file), [
        planner.PlanStep(description="one", command="ok"),
        planner.PlanStep(description="two", command="fail"),
    ])
    monkeypatch.setattr(cli, "run_command", lambda c: ("", c == "ok"))
    monkeypatch.setattr(cli, "update_knowledge", lambda *a, **k: None)
    knowledge = {"system": {}, "commands": []}
    steps = planner.load_plan(str(plan_file))
    planner.execute_plan(steps, str(plan_file), knowledge, str(tmp_path/"kb.json"), cli.run_command, cli.update_knowledge)
    assert steps[0].status == "done"
    assert steps[1].status == "failed"


def test_execute_plan_with_cd_and_edit(tmp_path, monkeypatch):
    cli.CURRENT_DIR = str(tmp_path)
    plan_file = tmp_path / "plan.json"
    steps = [
        planner.PlanStep(description="make", command="mkdir sub"),
        planner.PlanStep(description="enter", command="cd sub"),
        planner.PlanStep(description="write", command="edit hi.txt hi"),
        planner.PlanStep(description="show", command="cat hi.txt"),
    ]
    planner.save_plan(str(plan_file), steps)
    knowledge = {"system": {}, "commands": []}
    planner.execute_plan(
        steps,
        str(plan_file),
        knowledge,
        str(tmp_path / "kb.json"),
        cli.run_command,
        lambda *a, **k: None,
    )
    assert (tmp_path / "sub" / "hi.txt").read_text() == "hi"
    assert steps[3].output.strip() == "hi"

