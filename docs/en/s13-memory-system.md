# s13: Memory System [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | [ s13 ]`

> *"Knowledge that survives across sessions is proof the agent is growing"* -- memory is context engineering across time.
>
> **Harness layer**: Persistent memory -- the agent's first connection to its own past.

## Problem

Every session starts from zero. The agent learns your preferences, discovers project structure, receives corrections -- then the conversation ends and all of it evaporates. Next session, same mistakes, same questions, same ramp-up. The context window is powerful but volatile: it exists only for the duration of one conversation.

Real assistants remember. They don't ask your name twice. They don't repeat the same mistake after being corrected. The missing piece: a persistence layer that lets knowledge survive across sessions.

## Solution

```
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
```

Two-tier design: a compact **index** (always in the system prompt, under 200 lines) gives the agent an overview of everything it knows, while **detail files** are loaded on demand via tools. This keeps the context window lean while making full knowledge accessible.

### How other systems handle memory

| System | Approach | Trade-off |
|--------|----------|-----------|
| **Claude Code** (CLAUDE.md / MEMORY.md) | Markdown files injected into system prompt | Manual, project-scoped, no structured metadata |
| **Anthropic Memory Tool API** | Server-side key-value store via tool calls | Platform-managed, opaque storage, API-dependent |
| **ChatGPT** | Hidden memory summaries appended to system prompt | Automatic but no user control over structure |
| **MemGPT / Letta** | Virtual context with paging between main/archival memory | Most flexible but highest complexity |

Our approach borrows the best ideas: file-based like Claude Code (inspectable, version-controllable), tool-accessed like the Anthropic Memory API (agent-driven), structured with frontmatter metadata (searchable, typed), and two-tiered like MemGPT (index + detail).

## How It Works

1. **Initialize the MemoryManager.** Create the `.memory/` directory and seed an empty index.

```python
class MemoryManager:
    VALID_TYPES = {"user", "feedback", "project", "reference"}

    def __init__(self, memory_dir: Path):
        self.dir = memory_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# Memory\n\n(empty)\n")
```

The directory structure:

```
.memory/
├── MEMORY.md           # Index: always in system prompt (<200 lines)
├── user_prefs.md       # Detail: loaded via memory_read tool
├── project_auth.md
└── feedback_testing.md
```

2. **Parse frontmatter for structured metadata.** Every detail file carries a YAML-like header that the index is built from.

```python
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
```

A detail file looks like:

```markdown
---
name: User Preferences
description: Editor settings and communication style
type: user
updated: 2026-03-25
---

- Prefers concise answers
- Uses vim keybindings
- Timezone: UTC+8
```

3. **Write memory with frontmatter.** When the agent learns something worth remembering, it saves a file with structured metadata.

```python
def write_file(self, filename: str, name: str, description: str,
               memory_type: str, content: str) -> str:
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
```

4. **Rebuild the index automatically.** Every write, update, or delete triggers an index rebuild. The index groups files by type and provides one-line descriptions -- a table of contents the agent can scan instantly.

```python
def _rebuild_index(self):
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
        "user": "User", "feedback": "Feedback",
        "project": "Project", "reference": "Reference", "other": "Other",
    }
    for mtype in ["user", "feedback", "project", "reference", "other"]:
        if mtype in sections:
            lines.append(f"## {type_labels.get(mtype, mtype)}")
            lines.extend(sections[mtype])
            lines.append("")

    self.index_path.write_text("\n".join(lines).strip() + "\n")
```

The generated index looks like:

```markdown
# Memory

## User
- [User Preferences](user_prefs.md) - Editor settings and communication style

## Project
- [Auth Refactor](project_auth.md) - Backend auth migration status

## Feedback
- [Testing Conventions](feedback_testing.md) - Always run pytest before committing
```

5. **Inject the index into the system prompt.** The agent starts every session already knowing what it knows.

```python
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
```

6. **Five tools give the agent full CRUD control.** The agent decides what to remember, when to look things up, and when to forget.

| Tool | Purpose |
|------|---------|
| `memory_view` | View the index or list all files with metadata |
| `memory_read` | Load a specific detail file into context |
| `memory_write` | Create or overwrite a memory file |
| `memory_update` | Patch text in an existing file (str_replace) |
| `memory_delete` | Remove a file that is no longer relevant |

The agent loop itself is unchanged from s01 -- only the tools and system prompt are different. Memory is just another tool the agent can call.

## What Changed From s12

| Component         | Before (s12)                        | After (s13)                                       |
|-------------------|-------------------------------------|----------------------------------------------------|
| Persistence       | Task/worktree state on disk         | + General knowledge on disk                        |
| Session startup   | Blank slate                         | Index pre-loaded in system prompt                  |
| Knowledge capture | None                                | Agent-driven save via `memory_write`               |
| Organization      | Flat task JSON                      | Typed frontmatter (user/feedback/project/reference)|
| Context cost      | N/A                                 | Index only; details loaded on demand               |

## Try It

```sh
cd learn-claude-code
python agents/s13_memory_system.py
```

1. `What do you currently remember? Check your memory.`
2. `I prefer TypeScript over JavaScript and always use strict mode. Remember that.`
3. `We decided to use PostgreSQL for the auth service. Save this project decision.`
4. `What do you know about my preferences? Read the details.`
5. `Update my preferences: I also prefer dark theme in all editors.`
6. `The auth service decision is outdated. Delete that memory.`
7. `List all memory files and show me the current index.`
