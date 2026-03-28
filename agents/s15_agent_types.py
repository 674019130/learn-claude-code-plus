#!/usr/bin/env python3
"""
s15_agent_types.py - Agent Type Registry  [PLUS]

Maps agent type names to allowed tool sets, enforcing least-privilege:

    ┌──────────┬────────────────────────────────────────────┐
    │ Type     │ Allowed Tools                              │
    ├──────────┼────────────────────────────────────────────┤
    │ explore  │ read_file, glob, grep  (read-only)        │
    │ plan     │ read_file, glob, grep  (no execution)     │
    │ code     │ bash, read, write, edit (full capability)  │
    │ test     │ bash, read_file        (run + read only)  │
    └──────────┴────────────────────────────────────────────┘

Claude Code equivalent:
    Agent(subagent_type="Explore")   -> read-only tools
    Agent(subagent_type="Plan")      -> read-only, produces plans
    Agent()                          -> general-purpose, all tools
"""

from dataclasses import dataclass, field


@dataclass
class AgentType:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    can_write: bool = False
    can_execute: bool = False


# ── Registry ───────────────────────────────────────────────────────────────
AGENT_TYPE_REGISTRY: dict[str, AgentType] = {
    "explore": AgentType(
        name="explore",
        description="Read-only research agent. Cannot modify files or run arbitrary commands.",
        allowed_tools=["read_file", "glob", "grep", "list_dir"],
        can_write=False,
        can_execute=False,
    ),
    "plan": AgentType(
        name="plan",
        description="Planning agent. Can read code but cannot edit or execute. Produces plans.",
        allowed_tools=["read_file", "glob", "grep", "list_dir"],
        can_write=False,
        can_execute=False,
    ),
    "code": AgentType(
        name="code",
        description="Full-capability coding agent. Can read, write, edit, and execute.",
        allowed_tools=["bash", "read_file", "write_file", "edit_file", "glob", "grep", "list_dir"],
        can_write=True,
        can_execute=True,
    ),
    "test": AgentType(
        name="test",
        description="Test runner. Can execute commands and read files, but cannot modify code.",
        allowed_tools=["bash", "read_file", "glob", "grep", "list_dir"],
        can_write=False,
        can_execute=True,
    ),
}


# ── All tool definitions (superset) ───────────────────────────────────────
ALL_TOOL_DEFS: dict[str, dict] = {
    "bash": {
        "name": "bash", "description": "Run a shell command.",
        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
    "read_file": {
        "name": "read_file", "description": "Read file contents.",
        "input_schema": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "Start line (1-indexed)"},
            "limit": {"type": "integer", "description": "Number of lines"},
        }, "required": ["path"]},
    },
    "write_file": {
        "name": "write_file", "description": "Write content to file.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    },
    "edit_file": {
        "name": "edit_file", "description": "Replace exact text in file.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]},
    },
    "glob": {
        "name": "glob", "description": "Find files matching a glob pattern.",
        "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]},
    },
    "grep": {
        "name": "grep", "description": "Search file contents with regex.",
        "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]},
    },
    "list_dir": {
        "name": "list_dir", "description": "List directory contents.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}


def get_tools_for_type(type_name: str) -> list[dict]:
    """Return tool definitions filtered to what this agent type is allowed to use."""
    agent_type = AGENT_TYPE_REGISTRY.get(type_name)
    if not agent_type:
        raise ValueError(f"Unknown agent type: {type_name}. Available: {list(AGENT_TYPE_REGISTRY.keys())}")
    return [ALL_TOOL_DEFS[t] for t in agent_type.allowed_tools if t in ALL_TOOL_DEFS]


def get_type_summary() -> str:
    """Return a human-readable summary of all agent types."""
    lines = []
    for name, at in AGENT_TYPE_REGISTRY.items():
        tools = ", ".join(at.allowed_tools)
        lines.append(f"  {name:10s} [{tools}]  -- {at.description}")
    return "\n".join(lines)
