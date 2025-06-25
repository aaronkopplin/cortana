import os
import subprocess
import json
import yaml
import platform
import shutil
import asyncio
import argparse
import shlex

from planner import (
    PlanStep,
    generate_plan,
    save_plan,
    load_plan as load_task_plan,
    execute_plan,
)

import openai
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
]

# Maintain a persistent current working directory across commands
CURRENT_DIR = os.getcwd()


class CortanaResponse(BaseModel):
    explanation: str
    command: str


def gather_system_info() -> dict:
    """Collect basic system details."""
    info = {
        "os": platform.platform(),
        "packages": [],
        "running_services": [],
    }

    # Attempt to get installed packages using dpkg, rpm, or pip
    if shutil.which("dpkg-query"):
        result = subprocess.run(
            ["dpkg-query", "-f", "${binary:Package}\n", "-W"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            info["packages"] = result.stdout.strip().splitlines()
    elif shutil.which("rpm"):
        result = subprocess.run(["rpm", "-qa"], capture_output=True, text=True)
        if result.returncode == 0:
            info["packages"] = result.stdout.strip().splitlines()
    else:
        result = subprocess.run(
            ["pip", "list", "--format=json"], capture_output=True, text=True
        )
        if result.returncode == 0:
            try:
                pkgs = json.loads(result.stdout)
                info["packages"] = [p.get("name") for p in pkgs]
            except json.JSONDecodeError:
                info["packages"] = result.stdout.strip().splitlines()

    # List running services/process names
    ps = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True)
    if ps.returncode == 0:
        lines = ps.stdout.strip().splitlines()
        info["running_services"] = lines[1:] if len(lines) > 1 else []

    return info


def load_knowledge(path: str) -> dict:
    """Load existing knowledge or create new file with system info."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}

    if "system" not in data:
        data["system"] = gather_system_info()
    if "commands" not in data:
        data["commands"] = []

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return data


def update_knowledge(
    path: str, data: dict, command: str, output: str, success: bool
) -> None:
    """Append command execution result to knowledge base."""
    data.setdefault("commands", []).append(
        {"command": command, "output": output, "success": success}
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_rules() -> dict:
    """Load safety and preference rules from YAML files."""
    safety_path = os.getenv("CORTANA_SAFETY_RULES", "safety_rules.yaml")
    prefs_path = os.getenv("CORTANA_PREFERENCES", "preferences.yaml")
    rules = {"blocked": [], "confirm": []}
    for path in [safety_path, prefs_path]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                rules["blocked"].extend(data.get("blocked", []))
                rules["confirm"].extend(data.get("confirm", []))
            except Exception:
                continue
    return rules


def build_system_prompt(history: list[dict]) -> str:
    """Generate the system prompt including recent command history."""
    prompt = (
        "You are Cortana, a helpful assistant that suggests shell commands for"
        " server management. Respond ONLY in JSON with two keys: 'explanation'"
        " (a short to medium length answer) and 'command' (the suggested shell"
        " command)."
    )
    if history:
        entries = []
        for h in history[-5:]:
            status = "ok" if h.get("success") else "failed"
            entries.append(f"{h.get('command')} ({status})")
        prompt += " Recent command history: " + "; ".join(entries)
    return prompt


def check_command_rules(command: str, rules: dict) -> str | None:
    """Return 'block', 'danger', or 'confirm' if command matches a rule."""
    for pat in rules.get("blocked", []):
        if pat and pat in command:
            return "block"

    for pat in DANGEROUS_PATTERNS:
        if pat in command:
            return "danger"

    for pat in rules.get("confirm", []):
        if pat and pat in command:
            return "confirm"
    return None


def run_command(command: str) -> tuple[str, bool]:
    """Run a shell command with persistent state and return output and success."""
    global CURRENT_DIR
    stripped = command.strip()
    parts = shlex.split(stripped)
    if parts and parts[0] == "cd":
        target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
        if not os.path.isabs(target):
            target = os.path.join(CURRENT_DIR, target)
        if os.path.isdir(target):
            CURRENT_DIR = os.path.abspath(target)
            return "", True
        return f"cd: no such file or directory: {target}", False
    if parts and parts[0] == "edit":
        if len(parts) < 3:
            return "edit usage: edit <file> <content>", False
        path = parts[1]
        content = " ".join(parts[2:])
        if not os.path.isabs(path):
            path = os.path.join(CURRENT_DIR, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "", True
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=CURRENT_DIR,
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
            output_lines.append(line)
    process.wait()
    success = process.returncode == 0
    return "".join(output_lines), success


async def run_command_async(command: str) -> tuple[str, bool]:
    """Asynchronously run a shell command and stream output."""
    global CURRENT_DIR
    stripped = command.strip()
    parts = shlex.split(stripped)
    if parts and parts[0] == "cd":
        target = parts[1] if len(parts) > 1 else os.path.expanduser("~")
        if not os.path.isabs(target):
            target = os.path.join(CURRENT_DIR, target)
        if os.path.isdir(target):
            CURRENT_DIR = os.path.abspath(target)
            return "", True
        return f"cd: no such file or directory: {target}", False
    if parts and parts[0] == "edit":
        if len(parts) < 3:
            return "edit usage: edit <file> <content>", False
        path = parts[1]
        content = " ".join(parts[2:])
        if not os.path.isabs(path):
            path = os.path.join(CURRENT_DIR, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "", True
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=CURRENT_DIR,
    )
    output_lines: list[str] = []
    if process.stdout:
        async for line in process.stdout:
            text = line.decode()
            print(text, end="")
            output_lines.append(text)
    await process.wait()
    success = process.returncode == 0
    return "".join(output_lines), success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cortana CLI")
    parser.add_argument("--plan", help="Task description to plan and run")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Please set it in your environment or .env file.")
        return
    openai.api_key = api_key

    knowledge_file = os.getenv("CORTANA_KNOWLEDGE_FILE", "server_knowledge.json")
    knowledge = load_knowledge(knowledge_file)
    rules = load_rules()

    plan_file = "task_plan.json"
    if args.plan:
        steps = generate_plan(args.plan)
        save_plan(plan_file, steps)
        execute_plan(steps, plan_file, knowledge, knowledge_file, run_command, update_knowledge)
        return
    if os.path.exists(plan_file):
        steps = load_task_plan(plan_file)
        if any(s.status == "pending" for s in steps):
            resume = input("Resume pending plan? (press enter for yes, 'n' for no): ")
            if resume.strip().lower() != "n":
                execute_plan(steps, plan_file, knowledge, knowledge_file, run_command, update_knowledge)
                return

    system_prompt = build_system_prompt(knowledge.get("commands", []))
    messages = [{"role": "system", "content": system_prompt}]
    print("Type 'exit' to quit")
    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break
        if user_input.strip().lower().startswith("plan "):
            task = user_input.split(" ", 1)[1]
            steps = generate_plan(task)
            save_plan(plan_file, steps)
            execute_plan(steps, plan_file, knowledge, knowledge_file, run_command, update_knowledge)
            continue
        messages.append({"role": "user", "content": user_input})
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=messages,
            )
        except Exception as e:
            print(f"Error: {e}")
            break
        raw = response.choices[0].message["content"].strip()
        try:
            data = CortanaResponse.model_validate_json(raw)
        except ValidationError:
            print("Invalid JSON response from AI.")
            print(f"AI: {raw}")
            messages.append({"role": "assistant", "content": raw})
            continue

        print(f"AI: {data.explanation}")
        messages.append({"role": "assistant", "content": raw})

        command = data.command
        if command:
            print(f"\nCommand: {command}")
            action = check_command_rules(command, rules)
            if action == "block":
                print("Command blocked by safety rules.")
                continue
            if action == "danger":
                extra = input(
                    "WARNING: Dangerous command detected. Type 'yes' to run anyway: "
                )
                if extra.strip().lower() != "yes":
                    print("Command skipped.")
                    continue
            if action == "confirm":
                extra = input(
                    "This command requires extra confirmation. Type 'yes' to proceed: "
                )
                if extra.strip().lower() != "yes":
                    print("Command skipped.")
                    continue
            approve = input("Execute? (press enter for yes, 'n' for no): ")
            if approve.strip().lower() != "n":
                print(f"Running: {command}")
                output, success = run_command(command)
                update_knowledge(knowledge_file, knowledge, command, output, success)
                messages.append(
                    {
                        "role": "user",
                        "content": f"Executed command: {command}\nSuccess: {success}\nOutput:\n{output}",
                    }
                )
            else:
                print("Command skipped.")


if __name__ == "__main__":
    main()
