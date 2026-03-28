# s15: Production Agent Teams [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | s13 > s14 > [ s15 ]`

> *"Same patterns, real processes -- threads simulate, processes isolate"* -- production teams trade convenience for crash safety.
>
> **Harness layer**: Production teams -- process-based agent coordination with typed capabilities.

## Problem

s09 through s12 built a full team coordination system -- roles, protocols, autonomous loops, worktree isolation. But they made three simplifications that don't hold in production:

1. **Threads, not processes.** All agents share one Python interpreter. A crashed agent takes down the entire team. An infinite loop in one agent freezes them all. There is no OS-level isolation.

2. **Uniform tool access.** Every agent gets the same tools. A "researcher" agent that should only read files can also write and execute shell commands. There is no least-privilege enforcement.

3. **No foreground/background distinction.** All agents run concurrently in background threads. The lead cannot say "wait for this agent's result before continuing" vs "let this agent work while I move on." There is no execution mode control.

These simplifications were fine for learning coordination patterns. They are not fine for running agents against real codebases.

## Solution

```
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
```

Replace threads with OS processes. Each worker is a separate `python s15_worker.py` invocation with its own interpreter, its own API connection, its own `messages[]`. Communication goes through the filesystem -- JSONL inboxes and result files. A crashed worker exits with a non-zero code; the lead keeps running.

## How It Works

1. **Type registry restricts tools per agent.** Each agent type maps to a specific set of allowed tools. The registry enforces least-privilege at spawn time -- a worker simply never receives tool definitions it shouldn't use.

```python
AGENT_TYPE_REGISTRY = {
    "explore": AgentType(
        name="explore",
        description="Read-only research agent.",
        allowed_tools=["read_file", "glob", "grep", "list_dir"],
        can_write=False, can_execute=False,
    ),
    "code": AgentType(
        name="code",
        description="Full-capability coding agent.",
        allowed_tools=["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir"],
        can_write=True, can_execute=True,
    ),
    "test": AgentType(
        name="test",
        description="Test runner. Can execute but cannot modify code.",
        allowed_tools=["bash", "read_file", "glob", "grep", "list_dir"],
        can_write=False, can_execute=True,
    ),
}
```

| Type | Read | Write | Execute | Use Case |
|------|------|-------|---------|----------|
| **explore** | yes | no | no | Research, code analysis |
| **plan** | yes | no | no | Architecture planning |
| **code** | yes | yes | yes | Implementation |
| **test** | yes | no | yes | Run tests, verify |

2. **Workers spawn as real subprocesses.** `subprocess.Popen` launches each worker as an independent OS process. Each worker gets its own Python interpreter, its own LLM API connection, and its own context window.

```python
def spawn_agent(self, name: str, agent_type: str, prompt: str,
                background: bool = False) -> str:
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
```

3. **Foreground vs background execution.** The lead chooses at spawn time. Foreground agents block the lead until completion -- good for sequential work where the result is needed immediately. Background agents return control to the lead -- good for parallel work.

```python
    if not background:
        # FOREGROUND: block until worker completes
        proc.wait()
        result = self._read_result(name)
        return f"[{name} completed]\n{result}"
    else:
        # BACKGROUND: return immediately
        return f"Agent '{name}' spawned in background (PID {proc.pid})"
```

4. **File-based messaging via JSONL inboxes.** Each agent has an inbox file at `.s15_teams/{team}/inbox/{name}.jsonl`. Messages are appended as JSON lines. Reading drains the inbox (read-then-clear pattern). This avoids shared memory, locks, and race conditions.

```python
class Inbox:
    def read(self) -> list[dict]:
        if not self.file.exists():
            return []
        messages = []
        with open(self.file, "r") as f:
            for line in f:
                if line.strip():
                    messages.append(json.loads(line))
        self.file.write_text("")  # drain after reading
        return messages

    def send(self, to: str, content: str, from_name: str) -> str:
        target = self.inbox_dir / f"{to}.jsonl"
        msg = {"from": from_name, "content": content, "ts": time.time()}
        with open(target, "a") as f:
            f.write(json.dumps(msg) + "\n")
```

5. **Workers use `send_message` to report back.** Every agent type -- even read-only explore agents -- gets the `send_message` tool. When a worker finishes, it sends its final result to `lead` via the inbox. The lead's `drain_completions()` picks these up before each LLM turn.

```python
# Worker's final action: notify lead
inbox.send("lead", f"[{args.name} completed] {final[:500]}", args.name)

# Lead drains before each turn
def drain_completions(self) -> list[str]:
    notifications = []
    inbox_file = self.team_dir / "inbox" / "lead.jsonl"
    if inbox_file and inbox_file.exists():
        with open(inbox_file, "r") as f:
            for line in f:
                if line.strip():
                    msg = json.loads(line)
                    notifications.append(f"[From {msg['from']}]: {msg['content']}")
        inbox_file.write_text("")
    return notifications
```

6. **Lifecycle: create, spawn, coordinate, delete.** The team has explicit lifecycle management. `delete_team` sends `__shutdown__` to all active workers, waits for graceful exit, and kills stragglers after a 10-second timeout.

```python
def delete_team(self) -> str:
    for name, proc in self.processes.items():
        if proc.poll() is None:
            self.send_message(name, "__shutdown__")
    for name, proc in self.processes.items():
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    self.processes.clear()
```

## Comparison: s09-s12 vs s15 / Claude Code

| Dimension | s09-s12 (Thread Teams) | s15 (Process Teams) | Claude Code |
|-----------|----------------------|---------------------|-------------|
| **Isolation** | Threads in one process | Separate OS processes | Separate processes |
| **Crash behavior** | One crash kills all | Worker exits, lead continues | Worker exits, lead continues |
| **Tool access** | Uniform (all tools) | Typed (per agent type) | Typed (Explore/Plan/Code) |
| **Execution modes** | Background only | Foreground + background | Foreground + background |
| **Communication** | Shared Python dict | Filesystem JSONL inboxes | Internal message bus |
| **Context windows** | Shared or forked | Fully independent | Fully independent |
| **Lifecycle** | Implicit (thread join) | Explicit (create/spawn/delete) | Explicit (TeamCreate/TeamDelete) |
| **Coordination** | Python locks/events | File-based + process signals | SendMessage + drain |

## Claude Code Actual Usage

Claude Code's multi-agent system maps directly to the patterns in s15:

| Claude Code | s15 Equivalent | Description |
|------------|----------------|-------------|
| `TeamCreate` | `create_team()` | Initialize team workspace |
| `Agent(type=Explore)` | `spawn_agent(type="explore")` | Read-only research agent |
| `Agent(type=Plan)` | `spawn_agent(type="plan")` | Planning agent, no edits |
| `Agent()` (general) | `spawn_agent(type="code")` | Full-capability agent |
| `Agent(background=true)` | `spawn_agent(background=True)` | Non-blocking parallel work |
| `SendMessage` | `send_message()` | Inter-agent communication |
| `TeamDelete` | `delete_team()` | Tear down team |
| drain on each turn | `drain_completions()` | Collect background results |

Key insight: Claude Code's Agent tool does not spawn threads inside the current process. It launches separate Claude Code processes -- each with its own context, its own tool set, its own sandbox. s15 replicates this architecture with `subprocess.Popen` and file-based messaging.

## What Changed From s14

| Component | Before (s14) | After (s15) |
|-----------|-------------|-------------|
| Focus | Security (sandbox + permissions) | Multi-agent coordination |
| Agent model | Single agent with layered security | Lead + typed worker processes |
| Process model | One process | Multiple OS processes via Popen |
| Tool access | Uniform with deny/ask/allow | Per-type tool restriction |
| Communication | N/A (single agent) | JSONL inbox + result files |
| Execution modes | N/A | Foreground (blocking) + background (parallel) |
| Lifecycle | N/A | create_team / spawn / delete_team |
| Task tracking | N/A | File-based task board |

## Try It

```sh
cd learn-claude-code
python agents/s15_production_teams.py
```

1. `Create a team called "demo" for exploring this project.`
2. `Spawn an explore agent named "scanner" to list all Python files.` (foreground, read-only)
3. `Spawn a background explore agent named "reviewer" to analyze the agent loop in s01.`
4. `List the team to see agent statuses.`
5. `Send a message to reviewer asking for a summary.`
6. `Create a task "Write unit tests" and assign it to a test agent.`
7. `Delete the team when done.`
