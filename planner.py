from dataclasses import dataclass, asdict
from typing import List
import json
import os
import openai

PLAN_PROMPT = (
    "Break the following task into a short sequence of shell commands. "
    "Respond in JSON with a 'steps' array where each item has 'description' and 'command'."
)

@dataclass
class PlanStep:
    description: str
    command: str
    status: str = "pending"
    output: str = ""
    success: bool | None = None


def save_plan(path: str, steps: List[PlanStep]) -> None:
    data = [asdict(s) for s in steps]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_plan(path: str) -> List[PlanStep]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [PlanStep(**d) for d in data]
    except Exception:
        return []


def generate_plan(task: str) -> List[PlanStep]:
    """Use the language model to create a plan for the given task."""
    messages = [
        {"role": "system", "content": PLAN_PROMPT},
        {"role": "user", "content": task},
    ]
    client = openai.OpenAI()
    response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    raw = response.choices[0].message["content"].strip()
    data = json.loads(raw)
    steps = [PlanStep(**s) for s in data.get("steps", [])]
    return steps


def execute_plan(
    steps: List[PlanStep],
    plan_path: str,
    knowledge: dict,
    knowledge_path: str,
    run_command_fn,
    update_knowledge_fn,
    confirm_each_step: bool = False,
    input_fn=input,
) -> List[PlanStep]:
    """Run each pending step sequentially."""
    for step in steps:
        if step.status != "pending":
            continue
        print(f"Step: {step.description}")
        print(f"Command: {step.command}")
        if confirm_each_step:
            ans = input_fn("Run this command? (press enter for yes, 'n' to skip): ").strip().lower()
            if ans == "n":
                print("Step declined. Pausing plan.")
                step.status = "pending"
                save_plan(plan_path, steps)
                break
        output, success = run_command_fn(step.command)
        step.output = output
        step.success = success
        step.status = "done" if success else "failed"
        update_knowledge_fn(knowledge_path, knowledge, step.command, output, success)
        save_plan(plan_path, steps)
        if not success:
            print("Step failed. Stopping execution.")
            break
    return steps


def interactive_edit_plan(path: str) -> None:
    steps = load_plan(path)
    if not steps:
        print("No plan found.")
        return
    while True:
        for idx, s in enumerate(steps, 1):
            print(f"{idx}. {s.description}: {s.command} [{s.status}]")
        choice = input("Edit step number (enter to finish): ").strip()
        if not choice:
            break
        try:
            i = int(choice) - 1
            step = steps[i]
        except (ValueError, IndexError):
            print("Invalid step.")
            continue
        desc = input(f"Description [{step.description}]: ").strip()
        cmd = input(f"Command [{step.command}]: ").strip()
        if desc:
            step.description = desc
        if cmd:
            step.command = cmd
    save_plan(path, steps)
