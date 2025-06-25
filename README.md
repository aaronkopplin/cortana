# cortana
Cortana is an AI CLI agent that can help you with commands and small tasks on your server. 

## What It Does

This is a simple AI agent that sits in your terminal and helps with Linux commands. You talk to it in plain English, it suggests commands, and can run them for you while showing the output in real-time. It’s particularly useful for complex tasks like setting up web servers when you’re not entirely comfortable with all the command-line details.

## Core Features

**Conversational Interface**

- Chat with the AI about what you want to accomplish
- Get command suggestions with explanations
- Ask follow-up questions and get contextual help

**Command Execution**

- AI can run commands for you and show live output
- Shows generated command preview with simple “yes (enter) / no” approval
- Always asks permission before running anything potentially risky
- Responses are structured JSON parsed with Pydantic
- Captures results and learns from what works/doesn’t work
- Tracks command success or failure to refine future suggestions
- Maintains the current working directory across commands
- Built-in `edit` command to modify files from the CLI
- Multi-step automation plans via the `plan` keyword or `--plan` option

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
- Saves time on repetitive server management tasks

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

This is essentially a smart wrapper around the command line that makes server management more conversational and less error-prone.

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
python cli.py
```

