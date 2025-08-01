# cortana
Cortana is an AI CLI agent that helps you accomplish tasks by running shell commands.

## What It Does

This is a simple AI agent that sits in your terminal and helps with command-line tasks. You talk to it in plain English, it suggests commands, and can run them for you while showing the output in real-time. It can guide you through complex operations step by step.

## Core Features

**Conversational Interface**

- Chat with the AI about what you want to accomplish
- Get command suggestions with explanations
- Ask follow-up questions and get contextual help

**Command Execution**

- AI can run commands for you and show live output
- Shows generated command preview with simple “yes (enter) / no” approval
- Steps in an automation plan also require approval before running
- Declining a step pauses the plan so it can be resumed or edited later
- Always asks permission before running anything potentially risky
- Responses are structured JSON parsed with Pydantic
- Captures results and learns from what works/doesn’t work
- Cortana escapes any double quotes in her JSON responses
- Tracks command success or failure to refine future suggestions
- Maintains the current working directory across commands
- Built-in `edit` command to modify files from the CLI
- Avoid interactive editors like `nano` or `vim`; instead use `edit <file> <content>` or redirection commands
- Multi-step automation plans via the `plan` keyword or `--plan` option
- Plans are shown for approval and can be updated before execution

**Learning System**

- Keeps a knowledge file about your server (OS, installed packages, configurations)
- Remembers successful setups and configurations
- Records command outcomes (success or failure) in the knowledge base
- Updates its understanding as it discovers new things about your system

**Safety Controls**

- Rules file that you can edit to set boundaries
- Built-in safety checks for dangerous commands (e.g. detects `rm -rf /`)
- Always shows you what it’s about to run before executing

## Technical Approach

**Knowledge Base**

- `server_knowledge.json` - What the AI knows about your server
- Gets updated automatically as it runs commands and discovers things
- Includes installed packages, running services, file locations, etc.

**Rules System**

- `safety_rules.yaml` - Commands that need approval or are forbidden
- `preferences.yaml` - Your personal preferences and shortcuts
- `.cortanaignore` - List of commands that run without confirmation
- A default whitelist includes common commands like `ls`, `cd`, `cat`, `tail`,
  `mv`, `cp`, `grep`, and `find`
- A sample `.cortanaignore` file is included with these defaults
- Easy to edit and customize

**Architecture**

- Integrates with AI APIs (OpenAI, Claude, etc.)
- Local knowledge storage
- Real-time command output streaming

## Development Phases

**Phase 1**: Basic chat interface, simple command execution, basic knowledge storage

**Phase 3**: More complex multi-step automations, better error handling

## Why This Is Useful

- Reduces context switching between terminal and documentation
- Builds up institutional knowledge about your specific server setup
- Makes complex tasks more approachable for less experienced users
- Saves time on repetitive command-line tasks

## Simple Example Flow

```
You: I need to check if nginx is running and restart it if needed
AI: I'll check nginx status first.
    
    Command: systemctl status nginx
    Execute? (press enter for yes, 'n' for no): [enter]
    
    Running: systemctl status nginx
    ✓ nginx is active and running
    
    Since it's already running, no restart needed. Would you like me to 
    check the configuration or show you the current sites?

You: Show me the sites
AI: I'll list the configured nginx sites.
    
    Command: nginx -T 2>&1 | grep "server_name"
    Execute? (press enter for yes, 'n' for no): [enter]
    
    Running: nginx -T 2>&1 | grep "server_name"
    Found 3 configured sites:
    - example.com (SSL enabled)
    - test.local (development)
    - api.example.com (proxy to :3000)
    
    Would you like details on any specific site?
```

This is essentially a smart wrapper around the command line that makes complex tasks more conversational and less error-prone.

### Running Commands

The assistant responds in JSON with an explanation and a command suggestion. The CLI displays the explanation followed by the command and asks for confirmation:

```
AI: List files in the current directory.
Command: ls -la
Execute? (press enter for yes, 'n' for no):
```

Press **Enter** to run the command and see the live output, or type **n** to skip.
## Getting Started

1. Install dependencies:
```bash
pip install -r requirements.txt
```
2. Copy `.env.example` to `.env` and add your OpenAI API key.
3. Run the chat CLI:
```bash
python cortana.py
```
   or simply execute:
```bash
./run_cortana.sh
```
which creates/activates a `.venv` and launches the CLI for you.

