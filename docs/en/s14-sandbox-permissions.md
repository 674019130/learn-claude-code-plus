# s14: Sandbox & Permissions [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | s13 > [ s14 ]`

> *"Give the agent power, but draw the lines it cannot cross"* -- sandbox is the art of safe autonomy.
>
> **Harness layer**: Sandbox & permissions -- five layers between the agent and the operating system.

## Problem

An unprotected agent with shell access is a loaded weapon. It can `rm -rf /`, exfiltrate data via `curl`, read `.env` secrets, or be tricked by prompt injection into running arbitrary commands. The OWASP Top 10 for LLM Applications lists "Insecure Plugin Design" and "Excessive Agency" as critical threats -- both apply directly to coding agents with tool access.

The challenge: the agent *needs* real power (file I/O, shell, network) to be useful. But every tool call is a potential attack surface. How do you give an agent autonomy without giving it the keys to the kingdom?

## Solution

```
Tool call from LLM
        |
        v
┌───────────────────┐
│ L1: Path Sandbox   │  resolve() + is_relative_to()
└────────┬──────────┘
         v
┌───────────────────┐
│ L2: Resource Limit │  timeout 120s, output 50K
└────────┬──────────┘
         v
┌───────────────────┐
│ L3: OS Sandbox     │  Seatbelt / seccomp / gVisor
└────────┬──────────┘
         v
┌───────────────────┐
│ L4: Permission Mgr │  deny -> ask -> allow
└────────┬──────────┘
         v
┌───────────────────┐
│ L5: Hooks          │  PreToolUse / PostToolUse
└────────┬──────────┘
         v
    Execute tool

Defense in depth: every layer catches what the previous one missed.
No single layer is enough. Together they make safe autonomy possible.
```

Five layers, evaluated top-to-bottom on every tool call. Each layer can block execution independently. If all five pass, the tool runs. This is defense in depth -- the same principle behind firewalls, auth, and input validation in web security.

## How It Works

1. **Path sandbox with `safe_path`.** Every file operation resolves the path and checks it stays inside the workspace. This blocks directory traversal (`../../etc/passwd`) and symlink escapes.

```python
def safe_path(p: str) -> Path:
    """Resolve path and verify it stays within workspace.
    Defense: directory traversal, symlink escape.
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

2. **Resource limits on every command.** Shell commands get a 120-second timeout and output is capped at 50K characters. This prevents runaway processes and output flooding.

```python
def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
```

3. **OS-level sandbox.** In production, the agent process runs inside an OS sandbox that restricts system calls at the kernel level. This is the hardest layer to escape -- even if the agent finds a way past Layers 1-4, the OS itself blocks dangerous operations.

| Product | Technology | Mechanism |
|---------|-----------|-----------|
| **Claude Code** | macOS Seatbelt | Profile blocks network, restricts filesystem to workspace |
| **Cursor** | Seatbelt + Landlock + seccomp | Triple-layer OS enforcement |
| **OpenAI Codex** | gVisor on K8s | User-space kernel, full network lockdown |

4. **PermissionManager with deny/ask/allow rules.** Rules are evaluated in order: deny first (always blocks), then ask (prompts user), then allow (silent pass). First match wins. Default: deny.

```python
class PermissionManager:
    def __init__(self):
        self.rules = {
            "deny": [
                "Bash(rm -rf *)", "Bash(sudo *)", "Bash(shutdown*)",
                "Read(//.env)", "Read(//etc/passwd)",
            ],
            "ask": ["Bash", "write_file", "edit_file"],
            "allow": ["read_file", "permission_check", "permission_list"],
        }

    def check(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Evaluate deny -> ask -> allow. First match wins."""
        for pattern in self.rules["deny"]:
            if self._matches(pattern, tool_name, args):
                return False, f"denied by rule: {pattern}"
        for pattern in self.rules["ask"]:
            if self._matches(pattern, tool_name, args):
                return True, f"ask (auto-approved in demo): {pattern}"
        for pattern in self.rules["allow"]:
            if self._matches(pattern, tool_name, args):
                return True, f"allowed: {pattern}"
        return False, "denied: no matching rule (default deny)"
```

5. **Hooks for lifecycle control.** PreToolUse hooks run before the permission check and can override it. PostToolUse hooks run after execution for logging and auditing. In Claude Code, hooks are shell commands in `settings.json`.

```python
class HookManager:
    def run_pre(self, tool_name: str, args: dict) -> tuple[str | None, str]:
        for name, fn in self.pre_hooks:
            decision = fn(tool_name, args)
            if decision is not None:
                return decision, f"hook '{name}'"
        return None, ""

# Example: block data exfiltration
def _block_pipe_to_curl(tool_name, args):
    if tool_name == "bash" and "| curl" in args.get("command", ""):
        return "deny"
    return None

HOOKS.register_pre("block-exfiltration", _block_pipe_to_curl)
```

6. **Six permission modes control the trust level.** Claude Code offers a spectrum from maximum safety to full autonomy:

| Mode | Behavior | Use Case |
|------|----------|----------|
| **Default** | Prompts for write/execute, allows reads | Normal development |
| **Plan mode** | Read-only, no writes or execution | Code review, exploration |
| **allowedTools** | Whitelist specific tools | CI/CD pipelines |
| **dangerouslySkipPermissions** | No prompts at all | Trusted automation (100% autonomous) |

## Comparison: How Products Implement Sandboxing

| Aspect | This Teaching Agent | Claude Code | Cursor | OpenAI Codex |
|--------|-------------------|-------------|--------|------------|
| **Path sandbox** | Python `resolve()` | `safe_path` + rules | Workspace restriction | Container filesystem |
| **Resource limits** | 120s timeout, 50K cap | Timeout + truncation | Configurable limits | Container resources |
| **OS sandbox** | None (demo) | Seatbelt (macOS) / seccomp (Linux) | Seatbelt + Landlock + seccomp | gVisor user-space kernel |
| **Permission system** | deny/ask/allow rules | deny/ask/allow + 6 modes | Workspace + admin policies | Implicit deny-all |
| **Hooks** | Python callbacks | Shell commands in settings.json | N/A | N/A |
| **Prompt reduction** | N/A | **84%** fewer permission prompts | **40%** fewer interruptions | **100%** (no prompts -- fully sandboxed) |

The key insight: stronger OS sandboxing means fewer permission prompts. OpenAI's gVisor approach needs zero prompts because the container itself is the permission system. Claude Code's Seatbelt reduces prompts by 84% because many operations are safe within the sandbox. Cursor's approach reduces interruptions by 40%.

### Anthropic's 5 Safety Principles for Agents

1. **Think before acting** -- use chain-of-thought before tool calls
2. **Operate with minimal footprint** -- request only needed permissions
3. **Ask for help when uncertain** -- escalate to human when confidence is low
4. **Validate information before acting on it** -- don't trust untrusted input
5. **Sandbox where possible** -- run in restricted environments by default

## What Changed From s13

| Component | Before (s13) | After (s14) |
|-----------|-------------|-------------|
| Security model | None (trusted environment) | Five-layer sandbox |
| File access | Direct `Path.read_text()` | `safe_path()` with workspace check |
| Shell execution | No limits | 120s timeout, 50K output cap |
| Permission control | None | deny/ask/allow rule engine |
| Lifecycle hooks | None | PreToolUse/PostToolUse |
| Tool trust | All tools equally trusted | Tools categorized by risk level |

## Try It

```sh
cd learn-claude-code
python agents/s14_sandbox_permissions.py
```

1. `List the current permission rules.`
2. `Try to read the .env file.` (should be denied)
3. `Try to run: rm -rf /` (should be denied)
4. `Read a normal file in the workspace.` (should be allowed)
5. `Run: echo hello world` (should go through ask rule)
6. `Add a deny rule for Bash(curl *)` then try `Run: curl example.com`
7. `Check which rules apply to the bash tool.`
