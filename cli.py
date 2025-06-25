import os
import subprocess
import json
import platform
import shutil

import openai
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


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


def update_knowledge(path: str, data: dict, command: str, output: str) -> None:
    """Append command execution result to knowledge base."""
    data.setdefault("commands", []).append({"command": command, "output": output})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def run_command(command: str) -> str:
    """Run a shell command, stream output, and return it."""
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
            output_lines.append(line)
    process.wait()
    return "".join(output_lines)


def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Please set it in your environment or .env file.")
        return
    openai.api_key = api_key

    knowledge_file = os.getenv("CORTANA_KNOWLEDGE_FILE", "server_knowledge.json")
    knowledge = load_knowledge(knowledge_file)

    system_prompt = (
        "You are Cortana, a helpful assistant that suggests shell commands for"
        " server management. Respond ONLY in JSON with two keys: 'explanation'"
        " (a short to medium length answer) and 'command' (the suggested shell"
        " command)."
    )
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    print("Type 'exit' to quit")
    while True:
        try:
            user_input = input("You: ")
        except EOFError:
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break
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
            print(f"AI: {raw}")
            messages.append({"role": "assistant", "content": raw})
            continue

        print(f"AI: {data.explanation}")
        messages.append({"role": "assistant", "content": raw})

        command = data.command
        if command:
            print(f"\nCommand: {command}")
            approve = input("Execute? (press enter for yes, 'n' for no): ")
            if approve.strip().lower() != "n":
                print(f"Running: {command}")
                output = run_command(command)
                update_knowledge(knowledge_file, knowledge, command, output)
            else:
                print("Command skipped.")


if __name__ == "__main__":
    main()
