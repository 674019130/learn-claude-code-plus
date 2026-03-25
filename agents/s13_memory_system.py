#!/usr/bin/env python3
# Harness: persistent memory -- knowledge that survives across sessions.
"""
s13_memory_system.py - Memory System  [PLUS]

Cross-session persistence so the agent accumulates knowledge over time:

    Session 1:                    Session 2:
    +--------+                    +--------+
    |  User  | ----+              |  User  | ----+
    +--------+     |              +--------+     |
                   v                             v
    +-------+  +--------+        +-------+  +--------+
    |  LLM  |->| Tools  |        |  LLM  |->| Tools  |
    +---+---+  +--------+        +---+---+  +--------+
        |                            ^
        v                            |
    +----------+                 +----------+
    | .memory/ |  -- persists -> | .memory/ |
    | index.md |                 | index.md |
    | files... |                 | files... |
    +----------+                 +----------+

    Index stays in system prompt. Details load on demand.
    The agent remembers what it learned -- across any number of sessions.

Key insight: "Memory is context engineering across time."
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from llm_provider import create_provider
from dotenv import load_dotenv

load_dotenv(override=True)

WORKDIR = Path.cwd()
client = create_provider()
MODEL = os.environ["MODEL_ID"]

MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MAX_INDEX_LINES = 200


# ── MemoryManager ──────────────────────────────────────────────────────────
class MemoryManager:
    """File-based persistent memory with index + on-demand detail loading.

    Structure:
        .memory/
        ├── MEMORY.md           # Index: always in system prompt (<200 lines)
        ├── user_prefs.md       # Detail: loaded via memory_read tool
        ├── project_auth.md
        └── feedback_testing.md

    Each detail file uses frontmatter:
        ---
        name: User Preferences
        description: one-line summary for the index
        type: user | feedback | project | reference
        updated: 2026-03-25
        ---
        (content body)
    """

    VALID_TYPES = {"user", "feedback", "project", "reference"}

    def __init__(self, memory_dir: Path):
        self.dir = memory_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# Memory\n\n(empty)\n")

    @property
    def index_path(self) -> Path:
        return self.dir / "MEMORY.md"

    # ── Read operations ────────────────────────────────────────────────

    def view_index(self) -> str:
        """Return the index file content (always < MAX_INDEX_LINES)."""
        text = self.index_path.read_text()
        lines = text.splitlines()
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[:MAX_INDEX_LINES] + [f"\n... ({len(lines) - MAX_INDEX_LINES} lines truncated)"]
        return "\n".join(lines)

    def list_files(self) -> str:
        """List all memory files with their descriptions."""
        files = sorted(self.dir.glob("*.md"))
        entries = []
        for f in files:
            if f.name == "MEMORY.md":
                continue
            meta, _ = self._parse_frontmatter(f.read_text())
            desc = meta.get("description", "(no description)")
            mtype = meta.get("type", "unknown")
            updated = meta.get("updated", "unknown")
            entries.append(f"  {f.name}  [{mtype}]  {desc}  (updated: {updated})")
        if not entries:
            return "(no memory files yet)"
        return "\n".join(entries)

    def read_file(self, filename: str) -> str:
        """Read a specific memory detail file."""
        path = self._safe_path(filename)
        if not path.exists():
            return f"Error: Memory file '{filename}' not found."
        return path.read_text()[:50000]

    # ── Write operations ───────────────────────────────────────────────

    def write_file(self, filename: str, name: str, description: str,
                   memory_type: str, content: str) -> str:
        """Create or overwrite a memory file with frontmatter."""
        if memory_type not in self.VALID_TYPES:
            return f"Error: Invalid type '{memory_type}'. Must be one of: {self.VALID_TYPES}"
        path = self._safe_path(filename)
        today = datetime.now().strftime("%Y-%m-%d")
        text = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {memory_type}\n"
            f"updated: {today}\n"
            f"---\n\n"
            f"{content}\n"
        )
        path.write_text(text)
        self._rebuild_index()
        return f"Memory saved: {filename}"

    def update_file(self, filename: str, old_text: str, new_text: str) -> str:
        """Update content in an existing memory file."""
        path = self._safe_path(filename)
        if not path.exists():
            return f"Error: Memory file '{filename}' not found."
        content = path.read_text()
        if old_text not in content:
            return f"Error: Text not found in {filename}"
        content = content.replace(old_text, new_text, 1)
        # Update the 'updated' date in frontmatter
        today = datetime.now().strftime("%Y-%m-%d")
        content = re.sub(r"updated: \d{4}-\d{2}-\d{2}", f"updated: {today}", content)
        path.write_text(content)
        self._rebuild_index()
        return f"Memory updated: {filename}"

    def delete_file(self, filename: str) -> str:
        """Delete a memory file."""
        if filename == "MEMORY.md":
            return "Error: Cannot delete the index file."
        path = self._safe_path(filename)
        if not path.exists():
            return f"Error: Memory file '{filename}' not found."
        path.unlink()
        self._rebuild_index()
        return f"Memory deleted: {filename}"

    # ── Index management ───────────────────────────────────────────────

    def _rebuild_index(self):
        """Rebuild MEMORY.md from all memory files' frontmatter."""
        files = sorted(self.dir.glob("*.md"))
        sections: dict[str, list[str]] = {}
        for f in files:
            if f.name == "MEMORY.md":
                continue
            meta, _ = self._parse_frontmatter(f.read_text())
            mtype = meta.get("type", "other")
            desc = meta.get("description", f.stem)
            name = meta.get("name", f.stem)
            if mtype not in sections:
                sections[mtype] = []
            sections[mtype].append(f"- [{name}]({f.name}) - {desc}")

        lines = ["# Memory\n"]
        type_labels = {
            "user": "User",
            "feedback": "Feedback",
            "project": "Project",
            "reference": "Reference",
            "other": "Other",
        }
        for mtype in ["user", "feedback", "project", "reference", "other"]:
            if mtype in sections:
                lines.append(f"## {type_labels.get(mtype, mtype)}")
                lines.extend(sections[mtype])
                lines.append("")

        index_text = "\n".join(lines).strip() + "\n"
        self.index_path.write_text(index_text)

    # ── Helpers ────────────────────────────────────────────────────────

    def _safe_path(self, filename: str) -> Path:
        path = (self.dir / filename).resolve()
        if not path.is_relative_to(self.dir.resolve()):
            raise ValueError(f"Path escapes memory directory: {filename}")
        return path

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()
        return meta, match.group(2).strip()


# ── Initialize ─────────────────────────────────────────────────────────────
MEMORY = MemoryManager(MEMORY_DIR)

SYSTEM = f"""You are a coding agent at {WORKDIR}.

MEMORY PROTOCOL:
1. ALWAYS check your memory index at the start of each session.
2. Before working on a task, read any relevant memory files.
3. After completing significant work, save what you learned to memory.
4. Keep memory organized: update existing files rather than creating duplicates.
5. Delete memory files that are no longer relevant.

MEMORY TYPES:
- user: Information about the user (role, preferences, knowledge level)
- feedback: Corrections and confirmed approaches (what to do / not do)
- project: Ongoing work, decisions, deadlines
- reference: Pointers to external resources

Current memory index:
{MEMORY.view_index()}
"""


# ── Tool implementations ───────────────────────────────────────────────────
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
    "bash":           lambda **kw: run_bash(kw["command"]),
    "read_file":      lambda **kw: run_read(kw["path"], kw.get("offset"), kw.get("limit")),
    "write_file":     lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":      lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "memory_view":    lambda **kw: MEMORY.view_index() if kw.get("target") == "index" else MEMORY.list_files(),
    "memory_read":    lambda **kw: MEMORY.read_file(kw["filename"]),
    "memory_write":   lambda **kw: MEMORY.write_file(kw["filename"], kw["name"], kw["description"], kw["memory_type"], kw["content"]),
    "memory_update":  lambda **kw: MEMORY.update_file(kw["filename"], kw["old_text"], kw["new_text"]),
    "memory_delete":  lambda **kw: MEMORY.delete_file(kw["filename"]),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents. Supports offset and limit for random access.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"},
         "offset": {"type": "integer", "description": "Start from line number (1-indexed)"},
         "limit": {"type": "integer", "description": "Number of lines to read"}
     }, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "memory_view", "description": "View the memory index or list all memory files. Use target='index' for the index, target='files' for the full file list.",
     "input_schema": {"type": "object", "properties": {"target": {"type": "string", "enum": ["index", "files"]}}, "required": ["target"]}},
    {"name": "memory_read", "description": "Read a specific memory detail file by filename.",
     "input_schema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
    {"name": "memory_write", "description": "Create or overwrite a memory file. Each file has a name, one-line description, type (user/feedback/project/reference), and content body.",
     "input_schema": {"type": "object", "properties": {
         "filename": {"type": "string", "description": "e.g. user_prefs.md"},
         "name": {"type": "string", "description": "Human-readable name"},
         "description": {"type": "string", "description": "One-line summary for the index"},
         "memory_type": {"type": "string", "enum": ["user", "feedback", "project", "reference"]},
         "content": {"type": "string", "description": "The memory content body"},
     }, "required": ["filename", "name", "description", "memory_type", "content"]}},
    {"name": "memory_update", "description": "Update text in an existing memory file (str_replace).",
     "input_schema": {"type": "object", "properties": {
         "filename": {"type": "string"},
         "old_text": {"type": "string"},
         "new_text": {"type": "string"},
     }, "required": ["filename", "old_text", "new_text"]}},
    {"name": "memory_delete", "description": "Delete a memory file that is no longer relevant.",
     "input_schema": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": ["filename"]}},
]


# ── Agent loop (unchanged from s01 -- tools and system prompt are the only diff) ──
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
    print(f"\033[35m[memory dir: {MEMORY_DIR}]\033[0m")
    print(f"\033[35m[memory index loaded: {len(MEMORY.view_index().splitlines())} lines]\033[0m")
    while True:
        try:
            query = input("\033[36ms13 >> \033[0m")
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
