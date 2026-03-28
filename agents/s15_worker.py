#!/usr/bin/env python3
"""
s15_worker.py - Worker subprocess for production agent teams  [PLUS]

This script is launched by the lead process via subprocess.Popen.
Each worker is an independent process with its own:
  - Python interpreter
  - LLM API connection
  - messages[] array (context window)
  - Tool set (restricted by agent type)

Usage:
    python s15_worker.py --name researcher --team auth-feature --type explore \\
        --prompt "Analyze the auth module" --base-dir /path/to/.s15_teams

Claude Code equivalent: each Agent() call spawns a separate Claude Code process.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from llm_provider import create_provider
from dotenv import load_dotenv
from s15_agent_types import AGENT_TYPE_REGISTRY, get_tools_for_type

load_dotenv(override=True)

client = create_provider()
MODEL = os.environ["MODEL_ID"]


# ── Tool implementations ──────────────────────────────────────────────────
def safe_path(workdir: Path, p: str) -> Path:
    path = (workdir / p).resolve()
    if not path.is_relative_to(workdir):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(workdir: Path, command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=workdir,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(workdir: Path, path: str, offset: int = None, limit: int = None) -> str:
    try:
        lines = safe_path(workdir, path).read_text().splitlines()
        start = (offset or 1) - 1
        if limit:
            lines = lines[start:start + limit]
        elif offset:
            lines = lines[start:]
        if len(lines) > 2000:
            lines = lines[:2000] + [f"... ({len(lines) - 2000} more)"]
        return "\n".join(f"{i + start + 1:>6}\t{l}" for i, l in enumerate(lines))[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(workdir: Path, path: str, content: str) -> str:
    try:
        fp = safe_path(workdir, path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(workdir: Path, path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(workdir, path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_glob(workdir: Path, pattern: str, path: str = None) -> str:
    base = safe_path(workdir, path) if path else workdir
    matches = sorted(base.rglob(pattern))
    return "\n".join(str(m.relative_to(workdir)) for m in matches[:100]) or "(no matches)"

def run_grep(workdir: Path, pattern: str, path: str = None) -> str:
    try:
        base = path or "."
        r = subprocess.run(["grep", "-rn", pattern, base], cwd=workdir,
                           capture_output=True, text=True, timeout=30)
        return (r.stdout.strip()[:50000]) or "(no matches)"
    except Exception as e:
        return f"Error: {e}"

def run_list_dir(workdir: Path, path: str) -> str:
    try:
        p = safe_path(workdir, path)
        entries = sorted(p.iterdir())
        return "\n".join(f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries[:200])
    except Exception as e:
        return f"Error: {e}"


# ── Inbox (message delivery) ──────────────────────────────────────────────
class Inbox:
    """File-based inbox for receiving messages from other agents."""

    def __init__(self, inbox_dir: Path, name: str):
        self.file = inbox_dir / f"{name}.jsonl"
        self.inbox_dir = inbox_dir

    def read(self) -> list[dict]:
        if not self.file.exists():
            return []
        messages = []
        with open(self.file, "r") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
        # Clear after reading (drain pattern)
        self.file.write_text("")
        return messages

    def send(self, to: str, content: str, from_name: str) -> str:
        target = self.inbox_dir / f"{to}.jsonl"
        msg = {"from": from_name, "content": content, "ts": time.time()}
        with open(target, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent to {to}"


# ── Worker agent loop ─────────────────────────────────────────────────────
def worker_main(args):
    workdir = Path.cwd()
    base_dir = Path(args.base_dir)
    inbox_dir = base_dir / args.team / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    inbox = Inbox(inbox_dir, args.name)

    # Get tools for this agent type
    agent_type = AGENT_TYPE_REGISTRY.get(args.type)
    if not agent_type:
        print(f"Unknown agent type: {args.type}", file=sys.stderr)
        sys.exit(1)

    tools = get_tools_for_type(args.type)
    # Add send_message tool (all agents can communicate)
    tools.append({
        "name": "send_message", "description": "Send a message to another agent.",
        "input_schema": {"type": "object", "properties": {
            "to": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["to", "content"]},
    })

    # Build tool handlers (only for allowed tools)
    handlers = {}
    if "bash" in agent_type.allowed_tools:
        handlers["bash"] = lambda **kw: run_bash(workdir, kw["command"])
    if "read_file" in agent_type.allowed_tools:
        handlers["read_file"] = lambda **kw: run_read(workdir, kw["path"], kw.get("offset"), kw.get("limit"))
    if "write_file" in agent_type.allowed_tools:
        handlers["write_file"] = lambda **kw: run_write(workdir, kw["path"], kw["content"])
    if "edit_file" in agent_type.allowed_tools:
        handlers["edit_file"] = lambda **kw: run_edit(workdir, kw["path"], kw["old_text"], kw["new_text"])
    if "glob" in agent_type.allowed_tools:
        handlers["glob"] = lambda **kw: run_glob(workdir, kw["pattern"], kw.get("path"))
    if "grep" in agent_type.allowed_tools:
        handlers["grep"] = lambda **kw: run_grep(workdir, kw["pattern"], kw.get("path"))
    if "list_dir" in agent_type.allowed_tools:
        handlers["list_dir"] = lambda **kw: run_list_dir(workdir, kw["path"])
    handlers["send_message"] = lambda **kw: inbox.send(kw["to"], kw["content"], args.name)

    # System prompt with identity
    system = (
        f"You are agent '{args.name}' (type: {args.type}) in team '{args.team}'.\n"
        f"Working directory: {workdir}\n"
        f"Capabilities: {agent_type.description}\n"
        f"Available tools: {', '.join(agent_type.allowed_tools + ['send_message'])}\n"
        f"You CANNOT use tools not listed above.\n"
        f"When done, send your final result to the lead via send_message(to='lead', content=...)."
    )

    messages = [{"role": "user", "content": args.prompt}]
    result_file = base_dir / args.team / "results" / f"{args.name}.txt"
    result_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"\033[33m[worker:{args.name}] type={args.type} pid={os.getpid()}\033[0m", file=sys.stderr)

    # Agent loop
    while True:
        # Check inbox for new messages
        new_msgs = inbox.read()
        for msg in new_msgs:
            if msg.get("content") == "__shutdown__":
                print(f"\033[33m[worker:{args.name}] shutdown received\033[0m", file=sys.stderr)
                sys.exit(0)
            messages.append({"role": "user", "content": f"[Message from {msg['from']}]: {msg['content']}"})

        try:
            response = client.create(
                model=MODEL, system=system, messages=messages,
                tools=tools, max_tokens=8000,
            )
        except Exception as e:
            print(f"\033[31m[worker:{args.name}] API error: {e}\033[0m", file=sys.stderr)
            break

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Done — save final response
            final = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final += block.text
            result_file.write_text(final)
            print(f"\033[32m[worker:{args.name}] completed\033[0m", file=sys.stderr)
            # Notify lead
            inbox.send("lead", f"[{args.name} completed] {final[:500]}", args.name)
            break

        # Execute tools
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = handlers.get(block.name)
                if not handler:
                    output = f"Error: Tool '{block.name}' not available for agent type '{args.type}'"
                else:
                    try:
                        output = handler(**block.input)
                    except Exception as e:
                        output = f"Error: {e}"
                print(f"\033[90m  [{args.name}] {block.name}: {str(output)[:120]}\033[0m", file=sys.stderr)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="s15 worker subprocess")
    parser.add_argument("--name", required=True)
    parser.add_argument("--team", required=True)
    parser.add_argument("--type", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--base-dir", required=True)
    args = parser.parse_args()
    worker_main(args)
