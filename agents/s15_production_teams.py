#!/usr/bin/env python3
# Harness: production agent teams -- same patterns, real processes.
"""
s15_production_teams.py - Production Agent Teams  [PLUS]

Process-based agent teams with typed capabilities:

    Lead Process (PID 1000)               Worker Process (PID 1001)
    ┌──────────────────────┐              ┌──────────────────────┐
    │ agent loop           │              │ agent loop           │
    │ tools: ALL + team    │   Popen()    │ tools: per type      │
    │ context: own msgs[]  │─────────────>│ context: own msgs[]  │
    │                      │              │                      │
    │ drain_completions()  │<─ ─ ─ ─ ─ ─ │ send_message("lead") │
    └──────────────────────┘   result     └──────────────────────┘
              │                                    │
              v          Shared Filesystem         v
    ┌─────────────────────────────────────────────────┐
    │ .s15_teams/{name}/                              │
    │   config.json     <- team roster + types        │
    │   inbox/          <- message delivery (JSONL)   │
    │   results/        <- worker output files        │
    │   tasks/          <- task board                 │
    └─────────────────────────────────────────────────┘

s09-s12 used threads. This uses real OS processes.
Each worker has its own Python interpreter, its own API calls, its own context.
A crashed worker does not take down the lead.

Claude Code equivalent:
    TeamCreate          -> create_team()
    Agent(type=Explore) -> spawn_agent(type="explore")
    Agent(background)   -> spawn_agent(background=True)
    SendMessage         -> send_message()
    TeamDelete          -> delete_team()

Key insight: "Same coordination patterns, real process isolation."
"""

import atexit
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from llm_provider import create_provider
from dotenv import load_dotenv
from s15_agent_types import AGENT_TYPE_REGISTRY, get_type_summary

load_dotenv(override=True)

WORKDIR = Path.cwd()
client = create_provider()
MODEL = os.environ["MODEL_ID"]
BASE_DIR = WORKDIR / ".s15_teams"


# ── TeamManager ────────────────────────────────────────────────────────────
class TeamManager:
    """Manages a team of agent processes.

    Lifecycle: create_team -> spawn_agent (N times) -> coordinate -> delete_team
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.team_name: str | None = None
        self.team_dir: Path | None = None
        self.processes: dict[str, subprocess.Popen] = {}
        atexit.register(self._cleanup_on_exit)

    def create_team(self, name: str, description: str = "") -> str:
        self.team_name = name
        self.team_dir = self.base_dir / name
        self.team_dir.mkdir(parents=True, exist_ok=True)
        (self.team_dir / "inbox").mkdir(exist_ok=True)
        (self.team_dir / "results").mkdir(exist_ok=True)
        (self.team_dir / "tasks").mkdir(exist_ok=True)
        config = {
            "name": name,
            "description": description,
            "created": time.time(),
            "members": {},
        }
        (self.team_dir / "config.json").write_text(json.dumps(config, indent=2))
        return f"Team '{name}' created at {self.team_dir}"

    def spawn_agent(self, name: str, agent_type: str, prompt: str,
                    background: bool = False) -> str:
        if not self.team_name:
            return "Error: Create a team first with create_team."
        if agent_type not in AGENT_TYPE_REGISTRY:
            return f"Error: Unknown type '{agent_type}'. Available: {list(AGENT_TYPE_REGISTRY.keys())}"

        # Launch worker as separate process
        cmd = [
            sys.executable, str(Path(__file__).parent / "s15_worker.py"),
            "--name", name,
            "--team", self.team_name,
            "--type", agent_type,
            "--prompt", prompt,
            "--base-dir", str(self.base_dir),
        ]
        proc = subprocess.Popen(cmd, cwd=WORKDIR)
        self.processes[name] = proc

        # Update config
        self._update_member(name, agent_type, proc.pid, "working")

        if not background:
            # FOREGROUND: block until worker completes
            proc.wait()
            result = self._read_result(name)
            self._update_member(name, agent_type, proc.pid, "completed")
            return f"[{name} completed]\n{result}"
        else:
            # BACKGROUND: return immediately
            return f"Agent '{name}' (type: {agent_type}) spawned in background (PID {proc.pid})"

    def send_message(self, to: str, content: str) -> str:
        if not self.team_dir:
            return "Error: No team created."
        inbox_file = self.team_dir / "inbox" / f"{to}.jsonl"
        msg = {"from": "lead", "content": content, "ts": time.time()}
        with open(inbox_file, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Message sent to {to}"

    def list_team(self) -> str:
        if not self.team_dir:
            return "No team created."
        config = json.loads((self.team_dir / "config.json").read_text())
        lines = [f"Team: {config['name']}", f"Description: {config.get('description', '')}",
                 f"Members ({len(config['members'])}):", ""]
        for name, info in config["members"].items():
            # Check if process is still running
            proc = self.processes.get(name)
            live_status = info["status"]
            if proc and proc.poll() is not None and info["status"] == "working":
                live_status = "completed"
            lines.append(f"  {name:15s}  type={info['type']:10s}  pid={info['pid']}  status={live_status}")
        return "\n".join(lines)

    def delete_team(self) -> str:
        if not self.team_name:
            return "No team to delete."
        # Send shutdown to all active workers
        for name, proc in self.processes.items():
            if proc.poll() is None:  # still running
                self.send_message(name, "__shutdown__")
        # Wait for processes to exit
        for name, proc in self.processes.items():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.processes.clear()
        result = f"Team '{self.team_name}' shut down. Directory: {self.team_dir}"
        self.team_name = None
        self.team_dir = None
        return result

    def drain_completions(self) -> list[str]:
        """Check for completed background agents. Called before each LLM turn."""
        notifications = []
        # Check inbox for lead messages
        inbox_file = self.team_dir / "inbox" / "lead.jsonl" if self.team_dir else None
        if inbox_file and inbox_file.exists():
            with open(inbox_file, "r") as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line)
                        notifications.append(f"[From {msg['from']}]: {msg['content']}")
            inbox_file.write_text("")
        # Check process statuses
        for name, proc in list(self.processes.items()):
            if proc.poll() is not None:
                self._update_member_status(name, "completed")
        return notifications

    # ── Task board ─────────────────────────────────────────────────────

    def task_create(self, subject: str, assigned_to: str = None) -> str:
        if not self.team_dir:
            return "Error: No team."
        tasks_dir = self.team_dir / "tasks"
        existing = list(tasks_dir.glob("task_*.json"))
        task_id = len(existing) + 1
        task = {
            "id": task_id, "subject": subject,
            "status": "pending", "assigned_to": assigned_to,
        }
        (tasks_dir / f"task_{task_id}.json").write_text(json.dumps(task, indent=2))
        return f"Task #{task_id}: {subject}" + (f" (assigned to {assigned_to})" if assigned_to else "")

    def task_list(self) -> str:
        if not self.team_dir:
            return "No team."
        tasks_dir = self.team_dir / "tasks"
        files = sorted(tasks_dir.glob("task_*.json"))
        if not files:
            return "(no tasks)"
        lines = []
        for f in files:
            t = json.loads(f.read_text())
            status_icon = {"pending": "○", "in_progress": "◐", "completed": "●"}.get(t["status"], "?")
            lines.append(f"  {status_icon} #{t['id']} [{t['status']}] {t['subject']}"
                         + (f" -> {t['assigned_to']}" if t.get("assigned_to") else ""))
        return "\n".join(lines)

    def task_update(self, task_id: int, status: str) -> str:
        if not self.team_dir:
            return "Error: No team."
        path = self.team_dir / "tasks" / f"task_{task_id}.json"
        if not path.exists():
            return f"Error: Task #{task_id} not found."
        task = json.loads(path.read_text())
        task["status"] = status
        path.write_text(json.dumps(task, indent=2))
        return f"Task #{task_id} -> {status}"

    # ── Helpers ────────────────────────────────────────────────────────

    def _update_member(self, name: str, agent_type: str, pid: int, status: str):
        config_path = self.team_dir / "config.json"
        config = json.loads(config_path.read_text())
        config["members"][name] = {"type": agent_type, "pid": pid, "status": status}
        config_path.write_text(json.dumps(config, indent=2))

    def _update_member_status(self, name: str, status: str):
        config_path = self.team_dir / "config.json"
        if not config_path.exists():
            return
        config = json.loads(config_path.read_text())
        if name in config["members"]:
            config["members"][name]["status"] = status
            config_path.write_text(json.dumps(config, indent=2))

    def _read_result(self, name: str) -> str:
        result_file = self.team_dir / "results" / f"{name}.txt"
        if result_file.exists():
            return result_file.read_text()[:5000]
        return "(no result file)"

    def _cleanup_on_exit(self):
        for name, proc in self.processes.items():
            if proc.poll() is None:
                proc.kill()


# ── Initialize ─────────────────────────────────────────────────────────────
TEAM = TeamManager(BASE_DIR)

SYSTEM = f"""You are the lead agent at {WORKDIR}.

AGENT TEAMS:
You can create a team of specialized agents. Each agent runs as a separate process
with its own context window and typed tool restrictions.

Agent types:
{get_type_summary()}

Workflow:
1. create_team to set up the team
2. spawn_agent to launch workers (foreground=blocking or background=parallel)
3. send_message to communicate with agents
4. task_create/task_list/task_update to track work
5. delete_team when done

Foreground agents: you wait for the result (good for quick research).
Background agents: you continue working while they run in parallel.
"""


# ── Tool handlers & definitions ────────────────────────────────────────────
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

TOOL_HANDLERS = {
    "bash":          lambda **kw: run_bash(kw["command"]),
    "read_file":     lambda **kw: safe_path(kw["path"]).read_text()[:50000],
    "write_file":    lambda **kw: (safe_path(kw["path"]).write_text(kw["content"]), f"Wrote {len(kw['content'])} bytes")[1],
    "edit_file":     lambda **kw: (lambda fp, c: (fp.write_text(c.replace(kw["old_text"], kw["new_text"], 1)), f"Edited {kw['path']}")[1])(safe_path(kw["path"]), safe_path(kw["path"]).read_text()),
    "create_team":   lambda **kw: TEAM.create_team(kw["name"], kw.get("description", "")),
    "spawn_agent":   lambda **kw: TEAM.spawn_agent(kw["name"], kw["agent_type"], kw["prompt"], kw.get("background", False)),
    "send_message":  lambda **kw: TEAM.send_message(kw["to"], kw["content"]),
    "list_team":     lambda **kw: TEAM.list_team(),
    "delete_team":   lambda **kw: TEAM.delete_team(),
    "task_create":   lambda **kw: TEAM.task_create(kw["subject"], kw.get("assigned_to")),
    "task_list":     lambda **kw: TEAM.task_list(),
    "task_update":   lambda **kw: TEAM.task_update(kw["task_id"], kw["status"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "create_team", "description": "Create a new agent team.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "description": {"type": "string"},
     }, "required": ["name"]}},
    {"name": "spawn_agent", "description": "Spawn a typed agent as a separate process. Set background=true for parallel execution.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Agent name"},
         "agent_type": {"type": "string", "enum": ["explore", "plan", "code", "test"], "description": "Agent type determines available tools"},
         "prompt": {"type": "string", "description": "Task for the agent"},
         "background": {"type": "boolean", "description": "true=parallel, false=blocking (default)"},
     }, "required": ["name", "agent_type", "prompt"]}},
    {"name": "send_message", "description": "Send a message to an agent. Use to continue a completed agent's session.",
     "input_schema": {"type": "object", "properties": {
         "to": {"type": "string"}, "content": {"type": "string"},
     }, "required": ["to", "content"]}},
    {"name": "list_team", "description": "List all team members and their status.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "delete_team", "description": "Shut down all agents and clean up the team.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_create", "description": "Create a task on the team task board.",
     "input_schema": {"type": "object", "properties": {
         "subject": {"type": "string"},
         "assigned_to": {"type": "string", "description": "Agent name to assign to"},
     }, "required": ["subject"]}},
    {"name": "task_list", "description": "List all tasks on the team task board.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "task_update", "description": "Update a task's status.",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "integer"},
         "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
     }, "required": ["task_id", "status"]}},
]


# ── Agent loop ─────────────────────────────────────────────────────────────
def agent_loop(messages: list):
    while True:
        # Drain background completions before each turn
        if TEAM.team_name:
            notifications = TEAM.drain_completions()
            for note in notifications:
                messages.append({"role": "user", "content": note})

        response = client.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}: {str(output)[:200]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    print(f"\033[31m[s15: production agent teams]\033[0m")
    print(f"\033[90m  Agent types: explore (read-only), plan (no-edit), code (full), test (run+read)\033[0m")
    print(f"\033[90m  Modes: foreground (blocking) | background (parallel)\033[0m")
    print()
    while True:
        try:
            query = input("\033[36ms15 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
