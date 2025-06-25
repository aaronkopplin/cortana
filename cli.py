import os
import subprocess
import json

import openai
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError


class CortanaResponse(BaseModel):
    explanation: str
    command: str

def run_command(command: str) -> None:
    """Run a shell command and stream output."""
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout:
        for line in process.stdout:
            print(line, end="")
    process.wait()


def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set. Please set it in your environment or .env file.")
        return
    openai.api_key = api_key

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
                run_command(command)
            else:
                print("Command skipped.")


if __name__ == "__main__":
    main()
