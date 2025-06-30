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
    interactive_edit_plan,
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

# Built-in list of commands considered safe enough to run without asking
DEFAULT_AUTO_COMMANDS = [
    "ls",
    "pwd",
    "cd",
    "cat",
    "head",
    "tail",
    "cp",
    "mv",
    "touch",
    "mkdir",
    "grep",
    "find",
    "whoami",
    "date",
    "uptime",
]

# Path to optional whitelist file similar to .gitignore
DEFAULT_WHITELIST_PATH = ".cortanaignore"

# Maintain a persistent current working directory across commands
CURRENT_DIR = os.getcwd()


class CortanaResponse(BaseModel):
    explanation: str
    command: str


def gather_system_info() -> dict:
    """Collect basic system details."""
    info = {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "disk_free_mb": 0,
        "memory_total_mb": 0,
        "packages": [],
        "running_services": [],
    }

    # Disk usage and total memory
    try:
        disk = shutil.disk_usage("/")
        info["disk_free_mb"] = disk.free // 1024 // 1024
    except Exception:
        pass
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            first = f.readline()
            mem_kb = int(first.split()[1])
            info["memory_total_mb"] = mem_kb // 1024
    except Exception:
        pass

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
    if "stats" not in data:
        data["stats"] = {}
    if "paths" not in data:
        data["paths"] = {}

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
    stats = data.setdefault("stats", {})
    entry = stats.setdefault(command, {"success": 0, "failure": 0})
    if success:
        entry["success"] += 1
    else:
        entry["failure"] += 1
    paths = data.setdefault("paths", {})
    found = []
    try:
        tokens = shlex.split(command)
    except Exception:
        tokens = []
    for tok in tokens[1:]:
        if tok.startswith("-"):
            continue
        p = tok
        if not os.path.isabs(p):
            p = os.path.join(CURRENT_DIR, p)
        if os.path.exists(p):
            found.append(os.path.abspath(p))
    for p in found:
        paths[p] = "directory" if os.path.isdir(p) else "file"
    if not success:
        for p in found:
            if not os.path.exists(p) and p in paths:
                del paths[p]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_rules() -> dict:
    """Load safety and preference rules from YAML files and whitelist."""
    safety_path = os.getenv("CORTANA_SAFETY_RULES", "safety_rules.yaml")
    prefs_path = os.getenv("CORTANA_PREFERENCES", "preferences.yaml")
    whitelist_path = os.getenv("CORTANA_WHITELIST", DEFAULT_WHITELIST_PATH)

    rules = {"blocked": [], "confirm": [], "auto": DEFAULT_AUTO_COMMANDS.copy()}

    for path in [safety_path, prefs_path]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                rules["blocked"].extend(data.get("blocked", []))
                rules["confirm"].extend(data.get("confirm", []))
                rules["auto"].extend(
                    data.get("auto", []) or data.get("whitelist", []) or []
                )
            except Exception:
                continue

    if os.path.exists(whitelist_path):
        try:
            with open(whitelist_path, "r", encoding="utf-8") as f:
                for line in f:
                    cmd = line.strip()
                    if cmd and not cmd.startswith("#"):
                        rules["auto"].append(cmd)
        except Exception:
            pass

    # Remove duplicates while preserving order
    rules["auto"] = list(dict.fromkeys(rules["auto"]))
    return rules


def summarize_knowledge(data: dict) -> str:
    info = data.get("system", {})
    os_info = info.get("os", "")
    paths = list(data.get("paths", {}).keys())[:5]
    summary = f"OS: {os_info}."
    if paths:
        summary += " Known paths: " + ", ".join(paths)
    return summary


def build_system_prompt(history: list[dict], knowledge: dict) -> str:
    """Generate the system prompt including recent command history."""
    prompt = (
        "You are Cortana, a helpful assistant that suggests shell commands for"
        " server management. Respond ONLY in JSON with two keys: 'explanation'"
        " (a short to medium length answer) and 'command' (the suggested shell"
        " command)."
    )
    prompt += " " + summarize_knowledge(knowledge)
    if history:
        entries = []
        for h in history[-5:]:
            status = "ok" if h.get("success") else "failed"
            entries.append(f"{h.get('command')} ({status})")
        prompt += " Recent command history: " + "; ".join(entries)
    return prompt


def check_command_rules(command: str, rules: dict) -> str | None:
    """Return 'block', 'danger', 'confirm', or 'auto' if command matches a rule."""
    for pat in rules.get("blocked", []):
        if pat and pat in command:
            return "block"

    for pat in DANGEROUS_PATTERNS:
        if pat in command:
            return "danger"

    for pat in rules.get("confirm", []):
        if pat and pat in command:
            return "confirm"

    parts = shlex.split(command)
    if parts and parts[0] in rules.get("auto", []):
        return "auto"
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
    if not success:
        print(f"Command exited with code {process.returncode}")
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
    if not success:
        print(f"Command exited with code {process.returncode}")
    return "".join(output_lines), success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cortana CLI")
    parser.add_argument("--plan", help="Task description to plan and run")
    parser.add_argument("--edit-plan", action="store_true", help="Interactively edit pending plan")
    return parser.parse_known_args()[0]


def display_plan(steps: list[PlanStep]) -> None:
    for idx, step in enumerate(steps, 1):
        status = f" [{step.status}]" if step.status != "pending" else ""
        print(f"{idx}. {step.description}: {step.command}{status}")


def review_plan(task: str, plan_file: str) -> list[PlanStep] | None:
    steps = generate_plan(task)
    while True:
        print("Proposed plan:")
        display_plan(steps)
        choice = input(
            "Approve this plan? (press enter for yes, 'u' to update, 'n' to cancel): "
        ).strip().lower()
        if choice in {"", "y", "yes"}:
            save_plan(plan_file, steps)
            return steps
        if choice == "n":
            print("Plan cancelled.")
            return None
        if choice == "u":
            update = input("Describe the updates: ").strip()
            if update:
                task = f"{task}. {update}"
            steps = generate_plan(task)


def main():
    args = parse_args()
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Please set it in your environment or .env file.")
        return
    client = openai.OpenAI(api_key=api_key)

    knowledge_file = os.getenv("CORTANA_KNOWLEDGE_FILE", "server_knowledge.json")
    knowledge = load_knowledge(knowledge_file)
    rules = load_rules()

    plan_file = "task_plan.json"
    if args.edit_plan:
        interactive_edit_plan(plan_file)
        return
    if args.plan:
        steps = review_plan(args.plan, plan_file)
        if steps:
            execute_plan(
                steps,
                plan_file,
                knowledge,
                knowledge_file,
                run_command,
                update_knowledge,
                confirm_each_step=True,
            )
        return
    if os.path.exists(plan_file):
        steps = load_task_plan(plan_file)
        if any(s.status == "pending" for s in steps):
            resume = input("Resume pending plan? (press enter for yes, 'n' for no): ")
            if resume.strip().lower() != "n":
                execute_plan(
                    steps,
                    plan_file,
                    knowledge,
                    knowledge_file,
                    run_command,
                    update_knowledge,
                    confirm_each_step=True,
                )
                return

    system_prompt = build_system_prompt(knowledge.get("commands", []), knowledge)
    messages = [{"role": "system", "content": system_prompt}]
    print("Type 'exit' to quit")
    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break
        if user_input.strip().lower() in {"new", "reset"}:
            print("Starting a new conversation.")
            system_prompt = build_system_prompt(knowledge.get("commands", []), knowledge)
            messages = [{"role": "system", "content": system_prompt}]
            continue
        if user_input.strip().lower().startswith("plan "):
            task = user_input.split(" ", 1)[1]
            steps = review_plan(task, plan_file)
            if steps:
                execute_plan(
                    steps,
                    plan_file,
                    knowledge,
                    knowledge_file,
                    run_command,
                    update_knowledge,
                    confirm_each_step=True,
                )
            continue
        messages.append({"role": "user", "content": user_input})
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
            )
        except Exception as e:
            print(f"Error: {e}")
            break
        raw = response.choices[0].message["content"].strip()
        try:
            data = CortanaResponse.model_validate_json(raw)
        except ValidationError as e:
            print("Invalid JSON response from AI. Please try rephrasing your request.")
            print(f"AI: {raw}")
            print(f"Details: {e}")
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

            if action == "auto":
                approve = ""
            else:
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
