#!/usr/bin/env python3
# Harness: sandbox & permissions -- draw the lines the agent cannot cross.
"""
s14_sandbox_permissions.py - Sandbox & Permissions  [PLUS]

Five-layer security boundary so the agent has power within safe limits:

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
    │ L3: OS Sandbox     │  (production: Seatbelt/seccomp/gVisor)
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

    Claude Code: Seatbelt (macOS) / seccomp (Linux), reduces prompts by 84%
    Cursor: Seatbelt + Landlock + seccomp, reduces interruptions by 40%
    OpenAI: gVisor user-space kernel on K8s, full network lockdown

Key insight: "Sandbox is not about limiting the agent -- it's about giving it safe autonomy."

References:
    - https://code.claude.com/docs/en/permissions
    - https://www.anthropic.com/engineering/claude-code-sandboxing
    - https://cursor.com/blog/agent-sandboxing
    - https://www.anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents
"""

import fnmatch
import json
import os
import subprocess
import time
from pathlib import Path

from llm_provider import create_provider
from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd()
client = create_provider()
MODEL = os.environ["MODEL_ID"]


# ── Layer 1: Path Sandbox ──────────────────────────────────────────────────
def safe_path(p: str) -> Path:
    """Resolve path and verify it stays within workspace.

    Defense: directory traversal (../../etc/passwd), symlink escape.
    Production equivalent: Claude Code safe_path + sandbox filesystem rules.
    """
    path = (WORKDIR / p).resolve()
    # Check resolved path is within workspace (catches symlink escapes too)
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


# ── Layer 4: Permission Manager ────────────────────────────────────────────
class PermissionManager:
    """Three-tier permission system: deny -> ask -> allow.

    Mirrors Claude Code's real permission system:
    - Rules evaluated in order: deny first, then ask, then allow
    - First matching rule wins; deny always takes precedence
    - Tool-specific rules with glob specifiers: Bash(npm *), Read(.env)

    Production equivalents:
    - Claude Code: settings.json deny/ask/allow + 6 permission modes
    - Cursor: workspace + admin policies with Seatbelt enforcement
    - OpenAI: gVisor container = implicit deny-all for OS access
    """

    def __init__(self):
        self.rules = {
            "deny": [
                "Bash(rm -rf *)", "Bash(sudo *)", "Bash(shutdown*)",
                "Bash(reboot*)", "Bash(* > /dev/*)",
                "Read(//.env)", "Read(//etc/passwd)",
            ],
            "ask": [
                "Bash", "write_file", "edit_file",
            ],
            "allow": [
                "read_file", "permission_check", "permission_list",
            ],
        }

    def check(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Evaluate deny -> ask -> allow. First match wins."""
        # Deny rules: always block
        for pattern in self.rules["deny"]:
            if self._matches(pattern, tool_name, args):
                return False, f"denied by rule: {pattern}"
        # Ask rules: in production, prompt user; here, auto-approve with log
        for pattern in self.rules["ask"]:
            if self._matches(pattern, tool_name, args):
                return True, f"ask (auto-approved in demo): {pattern}"
        # Allow rules: silent pass
        for pattern in self.rules["allow"]:
            if self._matches(pattern, tool_name, args):
                return True, f"allowed: {pattern}"
        # Default: deny (principle of least privilege)
        return False, "denied: no matching rule (default deny)"

    def add_rule(self, rule_type: str, pattern: str) -> str:
        if rule_type not in self.rules:
            return f"Error: Invalid rule type '{rule_type}'. Must be deny/ask/allow."
        if pattern in self.rules[rule_type]:
            return f"Rule already exists: {rule_type} {pattern}"
        self.rules[rule_type].append(pattern)
        return f"Added: {rule_type} {pattern}"

    def remove_rule(self, rule_type: str, pattern: str) -> str:
        if rule_type not in self.rules:
            return f"Error: Invalid rule type '{rule_type}'."
        if pattern not in self.rules[rule_type]:
            return f"Rule not found: {rule_type} {pattern}"
        self.rules[rule_type].remove(pattern)
        return f"Removed: {rule_type} {pattern}"

    def list_rules(self) -> str:
        lines = []
        for rule_type in ["deny", "ask", "allow"]:
            lines.append(f"[{rule_type}]")
            for pattern in self.rules[rule_type]:
                lines.append(f"  {pattern}")
        return "\n".join(lines)

    def check_tool(self, tool_name: str) -> str:
        matching = []
        for rule_type in ["deny", "ask", "allow"]:
            for pattern in self.rules[rule_type]:
                base = pattern.split("(")[0] if "(" in pattern else pattern
                if base == tool_name or tool_name.startswith(base):
                    matching.append(f"  {rule_type}: {pattern}")
        if not matching:
            return f"No rules match '{tool_name}' -> default deny"
        return f"Rules matching '{tool_name}':\n" + "\n".join(matching)

    def _matches(self, pattern: str, tool_name: str, args: dict) -> bool:
        """Match a permission pattern against a tool call.

        Pattern syntax (mirrors Claude Code):
            "Bash"              -> matches all Bash calls
            "Bash(npm *)"       -> matches Bash where command starts with "npm "
            "Read(//.env)"      -> matches read_file where path ends with ".env"
        """
        if "(" in pattern:
            base, specifier = pattern.split("(", 1)
            specifier = specifier.rstrip(")")
        else:
            base, specifier = pattern, None

        # Base name must match
        if base != tool_name:
            # Also check common aliases
            aliases = {"Bash": "bash", "Read": "read_file", "Edit": "edit_file",
                       "Write": "write_file"}
            if aliases.get(base) != tool_name and base != tool_name:
                return False

        if specifier is None:
            return True

        # Match specifier against tool arguments
        if tool_name == "bash":
            cmd = args.get("command", "")
            return fnmatch.fnmatch(cmd, specifier)
        elif tool_name in ("read_file", "write_file", "edit_file"):
            path = args.get("path", "")
            if specifier.startswith("//"):
                return fnmatch.fnmatch(path, specifier[2:])
            return fnmatch.fnmatch(path, specifier)
        return False


# ── Layer 5: Hooks (simplified) ────────────────────────────────────────────
class HookManager:
    """PreToolUse and PostToolUse lifecycle hooks.

    In Claude Code, hooks are shell commands configured in settings.json:
        { "hooks": { "PreToolUse": [{ "matcher": "Bash", "command": "./check.sh" }] } }

    Hook can return:
        exit 0 + {"decision": "allow"}  -> skip permission prompt
        exit 0 + {"decision": "deny"}   -> block the call
        exit 2                           -> block (even overrides allow rules)

    Here we use Python callbacks for simplicity.
    """

    def __init__(self):
        self.pre_hooks: list = []
        self.post_hooks: list = []

    def register_pre(self, name: str, fn):
        self.pre_hooks.append((name, fn))

    def register_post(self, name: str, fn):
        self.post_hooks.append((name, fn))

    def run_pre(self, tool_name: str, args: dict) -> tuple[str | None, str]:
        """Run PreToolUse hooks. Returns (decision, reason) or (None, "")."""
        for name, fn in self.pre_hooks:
            decision = fn(tool_name, args)
            if decision is not None:
                return decision, f"hook '{name}'"
        return None, ""

    def run_post(self, tool_name: str, args: dict, result: str):
        """Run PostToolUse hooks (logging, metrics, etc.)."""
        for name, fn in self.post_hooks:
            fn(tool_name, args, result)


# ── Initialize security layers ─────────────────────────────────────────────
PERMISSIONS = PermissionManager()
HOOKS = HookManager()

# Example hook: block any bash command that pipes to curl (data exfiltration)
def _block_pipe_to_curl(tool_name: str, args: dict):
    if tool_name == "bash" and "| curl" in args.get("command", ""):
        return "deny"
    return None

HOOKS.register_pre("block-exfiltration", _block_pipe_to_curl)

# Example post-hook: log all tool executions
def _audit_log(tool_name: str, args: dict, result: str):
    print(f"\033[90m  [audit] {tool_name}: {str(result)[:80]}\033[0m")

HOOKS.register_post("audit-log", _audit_log)


# ── System prompt ──────────────────────────────────────────────────────────
SYSTEM = f"""You are a coding agent at {WORKDIR}.

SECURITY MODEL:
This agent runs inside a five-layer sandbox:
1. Path Sandbox: all file paths are resolved and checked against the workspace
2. Resource Limits: commands timeout after 120s, output capped at 50K chars
3. OS Sandbox: (production: Seatbelt/seccomp/gVisor -- not in this demo)
4. Permission Manager: rules evaluated as deny -> ask -> allow
5. Hooks: PreToolUse hooks run before permission check

Current permission rules:
{PERMISSIONS.list_rules()}

Use permission_list to see all rules.
Use permission_check to see which rules apply to a specific tool.
Use permission_set to modify rules (add/remove deny/ask/allow patterns).
"""


# ── Tool implementations ───────────────────────────────────────────────────
# Layer 2: Resource limits (timeout + truncation)
def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"

def run_read(path: str, offset: int = None, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
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

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("offset"), kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "permission_check": lambda **kw: PERMISSIONS.check_tool(kw["tool_name"]),
    "permission_set":   lambda **kw: PERMISSIONS.add_rule(kw["rule_type"], kw["pattern"])
                                     if kw.get("action", "add") == "add"
                                     else PERMISSIONS.remove_rule(kw["rule_type"], kw["pattern"]),
    "permission_list":  lambda **kw: PERMISSIONS.list_rules(),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command (subject to permission rules).",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents. Supports offset and limit.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "offset": {"type": "integer", "description": "Start line (1-indexed)"},
         "limit": {"type": "integer", "description": "Number of lines"},
     }, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "permission_check", "description": "Check which permission rules apply to a specific tool.",
     "input_schema": {"type": "object", "properties": {"tool_name": {"type": "string"}}, "required": ["tool_name"]}},
    {"name": "permission_set", "description": "Add or remove a permission rule.",
     "input_schema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["add", "remove"]},
         "rule_type": {"type": "string", "enum": ["deny", "ask", "allow"]},
         "pattern": {"type": "string", "description": "e.g. Bash(npm *), Read(.env)"},
     }, "required": ["action", "rule_type", "pattern"]}},
    {"name": "permission_list", "description": "List all current permission rules.",
     "input_schema": {"type": "object", "properties": {}}},
]


# ── Agent loop with five-layer security ────────────────────────────────────
def agent_loop(messages: list):
    while True:
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
                # ── Layer 5: PreToolUse hooks ──
                hook_decision, hook_reason = HOOKS.run_pre(block.name, block.input)
                if hook_decision == "deny":
                    output = f"⛔ Blocked by {hook_reason}"
                    print(f"\033[31m> {block.name}: blocked by {hook_reason}\033[0m")
                else:
                    # ── Layer 4: Permission check ──
                    allowed, reason = PERMISSIONS.check(block.name, block.input)
                    if not allowed:
                        output = f"⛔ {reason}"
                        print(f"\033[31m> {block.name}: {reason}\033[0m")
                    else:
                        # ── Layers 1-2: safe_path + resource limits (inside handlers) ──
                        handler = TOOL_HANDLERS.get(block.name)
                        try:
                            output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                        except ValueError as e:
                            # Layer 1: path sandbox violation
                            output = f"⛔ Path sandbox: {e}"
                        except Exception as e:
                            output = f"Error: {e}"
                        print(f"\033[32m> {block.name} ({reason}): {str(output)[:200]}\033[0m")
                        # ── Layer 5: PostToolUse hooks ──
                        HOOKS.run_post(block.name, block.input, output)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    print(f"\033[31m[sandbox: five-layer security active]\033[0m")
    print(f"\033[90m  L1: Path sandbox (safe_path)\033[0m")
    print(f"\033[90m  L2: Resource limits (120s timeout, 50K output)\033[0m")
    print(f"\033[90m  L3: OS sandbox (production only)\033[0m")
    print(f"\033[90m  L4: Permission manager (deny→ask→allow)\033[0m")
    print(f"\033[90m  L5: Hooks (PreToolUse/PostToolUse)\033[0m")
    print()
    while True:
        try:
            query = input("\033[36ms14 >> \033[0m")
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
