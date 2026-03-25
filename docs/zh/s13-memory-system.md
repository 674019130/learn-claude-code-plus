# s13: Memory System (持久化记忆) [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 > [ s13 ]`

> *"跨越会话的知识, 是 agent 成长的证据"* -- harness 层: 持久化记忆
>
> **Harness 层**: 跨会话记忆 -- 让 agent 不再每次从零开始。

## 问题

到 s12, 智能体拥有了任务系统、团队协作、worktree 隔离 -- 但每次对话结束, 一切归零。用户反复解释 "我的项目用 Next.js + Supabase"、"数据库在悉尼区域"、"部署走 Cloudflare Tunnel"。智能体没有记忆, 就像每天都在培训新同事。

ChatGPT 用 33 条长期事实的扁平列表解决这个问题 -- 简单, 但容量有限, 无法存储结构化知识。MemGPT/Letta 引入了 RAM/disk 隐喻: 上下文窗口是 RAM (快但小), 外部存储是 disk (慢但大)。我们的方案介于两者之间: 索引文件是 RAM, 详情文件是 disk, 按需加载。

## 解决方案

```
Session 1                              Session 2
+-------------------+                  +-------------------+
| "我用 Supabase,   |                  | "帮我加个新表"    |
|  部署在悉尼"      |                  |                   |
|                   |                  | (system prompt    |
| memory_write ->   |                  |  已包含 MEMORY.md |
+-------------------+                  |  知道你用 Supabase|
         |                             |  知道部署在悉尼)  |
         v                             +-------------------+
   .memory/                                    ^
   ├── MEMORY.md         (索引 -- 始终在 system prompt)
   ├── project_stack.md  (详情 -- 按需 memory_read)
   ├── deploy_config.md  (详情 -- 按需 memory_read)
   └── user_prefs.md     (详情 -- 按需 memory_read)
```

两层架构, 与 s05 技能加载同构: 索引便宜地常驻 system prompt, 详情按需加载到 tool_result。

## 工作原理

1. **MemoryManager 初始化。** 创建 `.memory/` 目录和 `MEMORY.md` 索引文件。

```python
class MemoryManager:
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.memory_dir / "MEMORY.md"
        if not self.index_path.exists():
            self.index_path.write_text("# Memory\n\n")
```

2. **系统提示注入索引。** MEMORY.md 完整内容写入 system prompt -- 模型知道记住了什么, 但不占用太多 token (只有摘要)。与 s05 的两层架构同构: 第一层是索引 (便宜), 第二层是详情 (按需)。

```python
memory_index = MEMORY.index_path.read_text() if MEMORY.index_path.exists() else ""

SYSTEM = f"""You are a coding agent at {WORKDIR}.
{memory_index}

You have memory tools: memory_write, memory_read, memory_delete.
Use them to persist important facts across sessions."""
```

3. **memory_write 保存详情文件。** 每个记忆是一个带 YAML frontmatter 的 markdown 文件, 包含元数据。写入后自动重建索引。

```python
def write(self, name: str, description: str, content: str,
          type: str = "fact") -> str:
    frontmatter = {
        "name": name,
        "description": description,
        "type": type,           # fact | preference | procedure | context
        "updated": datetime.now().isoformat(),
    }
    path = self.memory_dir / f"{name}.md"
    text = f"---\n{yaml.dump(frontmatter)}---\n\n{content}"
    path.write_text(text)
    self._rebuild_index()
    return f"Memory '{name}' saved."
```

这对应 Anthropic 的 Memory Tool API (`memory_20250818`), 其中 `memory.update` 也用 frontmatter 式结构存储记忆条目。区别在于 Anthropic 的实现是服务端持久化, 我们的是文件系统持久化。

4. **memory_read 按需加载详情。** 模型看到索引中某条记忆相关, 调用 read 获取完整内容 -- 就像 MemGPT 从 disk 加载到 RAM。

```python
def read(self, name: str) -> str:
    path = self.memory_dir / f"{name}.md"
    if not path.exists():
        return f"Error: Memory '{name}' not found."
    text = path.read_text()
    _, body = self._parse_frontmatter(text)
    return body
```

5. **_rebuild_index 自动重建索引。** 扫描所有详情文件的 frontmatter, 生成 MEMORY.md。这保证索引始终与文件系统一致。

```python
def _rebuild_index(self):
    lines = ["# Memory\n"]
    for f in sorted(self.memory_dir.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        text = f.read_text()
        meta, _ = self._parse_frontmatter(text)
        name = meta.get("name", f.stem)
        desc = meta.get("description", "")
        type_ = meta.get("type", "fact")
        lines.append(f"- **{name}** ({type_}): {desc}")
    self.index_path.write_text("\n".join(lines) + "\n")
```

Claude Code 的真实实现也是这个模式: `.claude/` 目录下的 `MEMORY.md` 是索引, 子目录中的 `.md` 文件是详情。用户可以直接编辑这些文件, agent 也可以通过工具修改。

6. **memory_delete 清理过时记忆。** 防止记忆膨胀, 删除后自动重建索引。

```python
def delete(self, name: str) -> str:
    path = self.memory_dir / f"{name}.md"
    if not path.exists():
        return f"Error: Memory '{name}' not found."
    path.unlink()
    self._rebuild_index()
    return f"Memory '{name}' deleted."
```

记忆不是只增不减的。ChatGPT 的 33 条上限是硬约束; MemGPT 有显式的 `memory_erase`; 我们用 `memory_delete` + 索引重建保持整洁。

## 相对 s12 的变更

| 组件               | 之前 (s12)                     | 之后 (s13)                                   |
|--------------------|--------------------------------|----------------------------------------------|
| 会话间状态         | 无 (每次从零开始)              | `.memory/` 持久化记忆                        |
| 系统提示           | 静态                           | + MEMORY.md 索引注入                         |
| Tools              | 任务 + worktree 工具           | + memory_write / memory_read / memory_delete |
| 知识架构           | 仅技能 (s05)                   | 技能 + 记忆 (两套两层架构)                   |
| 索引一致性         | 手动维护                       | _rebuild_index 自动重建                      |
| 信息生命周期       | 会话结束即丢失                 | 跨会话持久, 可增删改查                       |

## 试一试

```sh
cd learn-claude-code
python agents/s13_memory_system.py
```

试试这些 prompt (英文 prompt 对 LLM 效果更好, 也可以用中文):

1. `Save a memory called "project_stack" about my tech stack: Next.js + Supabase + Tailwind.`
2. `What do you remember about me?`
3. `Read the full details of memory "project_stack".`
4. `Update memory "project_stack" to add that deployment uses Cloudflare Tunnel.`
5. `Delete the memory "project_stack" and verify it's gone.`
6. `Save three memories: my timezone (UTC+8), my language (Chinese), my editor (Neovim). Then list all.`
