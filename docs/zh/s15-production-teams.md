# s15: Production Agent Teams (生产级 Agent 团队) [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 | s13 > s14 > [ s15 ]`

> *"Same patterns, real processes -- threads simulate, processes isolate"*
>
> **Harness 层**: 进程级 agent 团队 -- 从线程模拟到真实进程隔离。

## 问题

s09-s12 的 multi-agent 有三个教学简化:

1. **线程共享内存, 不是进程隔离。** 所有 agent 跑在同一个 Python 进程里, 共享 `messages[]` 和全局状态。一个线程崩溃可能带崩整个进程。
2. **工具统一, 不是类型化。** 每个 agent 拿到相同的工具集。explore agent 能 `rm -rf`, code agent 能读 `.env` -- 没有最小权限。
3. **没有前台/后台区分。** 所有 agent 都在后台跑, lead 轮询等结果。无法选择 "这个任务我要等结果" vs "这个任务让它跑着, 我继续干别的"。

这三个简化在教学中无害, 但在生产环境中是三颗地雷。

## 解决方案

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

Lead 和 Worker 是独立进程。每个 Worker 有自己的 Python 解释器、自己的 API 连接、自己的 `messages[]`。通过共享文件系统 (`.s15_teams/`) 交换消息。

## 工作原理

1. **Agent 类型注册表 -- 最小权限。** 四种类型, 每种只能用特定工具:

```python
AGENT_TYPE_REGISTRY: dict[str, AgentType] = {
    "explore": AgentType(
        name="explore",
        description="Read-only research agent.",
        allowed_tools=["read_file", "glob", "grep", "list_dir"],
        can_write=False, can_execute=False,
    ),
    "plan": AgentType(
        name="plan",
        description="Planning agent. Can read but cannot edit or execute.",
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
        description="Test runner. Can execute and read, but cannot modify code.",
        allowed_tools=["bash", "read_file", "glob", "grep", "list_dir"],
        can_write=False, can_execute=True,
    ),
}
```

`explore` 不能写不能执行, `test` 能执行但不能写, `code` 全能。类型决定工具集, 工具集决定能力边界。Claude Code 的 `Agent(subagent_type="Explore")` 就是这个思路。

2. **进程级 spawn -- subprocess.Popen 独立 context。** 每个 agent 是一个独立进程, 有自己的 Python 解释器和 API 连接:

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

`subprocess.Popen` 而不是 `threading.Thread`。独立进程意味着: 独立的 context window、独立的 API 计费、独立的故障域。一个 worker 崩溃不影响 lead 和其他 worker。

3. **前台 vs 后台 -- proc.wait() blocking vs fire-and-forget。** 同一个 `spawn_agent` 方法, `background` 参数决定行为:

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

前台: lead 等 worker 做完才继续 (适合快速查询)。后台: lead 继续干自己的, worker 独立跑 (适合并行任务)。

4. **消息传递 -- inbox JSONL + drain_completions()。** 进程间通信用文件系统, 每个 agent 有一个 JSONL inbox:

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
        self.file.write_text("")  # drain pattern: read once, clear
        return messages

    def send(self, to: str, content: str, from_name: str) -> str:
        target = self.inbox_dir / f"{to}.jsonl"
        msg = {"from": from_name, "content": content, "ts": time.time()}
        with open(target, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent to {to}"
```

Lead 在每次 LLM turn 前调用 `drain_completions()`, 把 inbox 里的消息注入 context:

```python
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

Worker 完成后自动向 lead 发送结果。不需要轮询 -- drain 模式在每个 turn 自然检查。

5. **SendMessage 唤醒 -- 继续已有 session。** Worker 的 agent loop 在没有 tool_use 时退出, 但 inbox 机制允许 lead 发消息唤醒:

```python
# Worker agent loop
while True:
    new_msgs = inbox.read()
    for msg in new_msgs:
        if msg.get("content") == "__shutdown__":
            sys.exit(0)
        messages.append({"role": "user", "content": f"[Message from {msg['from']}]: {msg['content']}"})
```

`__shutdown__` 是特殊信号, lead 关闭团队时发送。其他消息被注入 worker 的 context, 作为新的 user message 继续对话。

6. **团队生命周期 -- create -> spawn -> coordinate -> delete。** 完整生命周期管理:

```python
class TeamManager:
    def create_team(self, name, description="") -> str:
        # 创建目录结构: config.json + inbox/ + results/ + tasks/

    def spawn_agent(self, name, agent_type, prompt, background=False) -> str:
        # 启动 worker 进程, 前台等待或后台返回

    def send_message(self, to, content) -> str:
        # 向指定 agent 的 inbox 写入消息

    def delete_team(self) -> str:
        # 发送 __shutdown__, 等待退出, 超时则 kill
        for name, proc in self.processes.items():
            if proc.poll() is None:
                self.send_message(name, "__shutdown__")
        for name, proc in self.processes.items():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
```

`delete_team` 先礼后兵: 先发 shutdown 消息让 worker 优雅退出, 10 秒内不退出则 kill。`atexit.register` 确保 lead 进程退出时也会清理。

## 对比表

| 维度 | s09-s12 教学 | s15 / Claude Code |
|------|-------------|-------------------|
| 执行模型 | 线程 (`threading.Thread`) | 进程 (`subprocess.Popen`) |
| Context | 共享 8K (同一 `messages[]`) | 独立 1M (每进程独立 context) |
| 工具权限 | 统一 (所有 agent 工具相同) | 类型化 (explore/plan/code/test) |
| 执行模式 | 全后台 (lead 轮询) | 前台/后台 (`background` 参数) |
| 消息投递 | 轮询 (`while not done`) | 自动投递 (`drain_completions()`) |
| 故障隔离 | 线程死 = 静默失败 | 进程死 = 只影响自己 |
| API 计费 | 单 API 流 | 独立计费 (每进程独立 API 调用) |

## Claude Code 实际用法

Claude Code 通过实验性 Agent Teams 功能实现了 s15 的所有概念:

- **TeamCreate** -- 创建团队, 分配名字和描述。对应 `create_team()`
- **Agent(subagent_type)** -- 指定 agent 类型: `Explore` (只读), `Plan` (规划), 默认 (全能)。对应 `spawn_agent(type=...)`
- **SendMessage** -- 向已有 agent 发送消息, 继续其 session。对应 `send_message()`
- **环境变量** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` -- 启用团队功能

与 s09-s12 的 `Agent()` 工具不同, Teams 功能的每个 agent 是独立的 Claude Code 进程, 有独立的 1M context window, 独立的权限和沙盒。

## 相对 s14 的变更

| 组件 | 之前 (s14) | 之后 (s15) |
|------|-----------|-----------|
| Agent 架构 | 单进程, 无团队 | 多进程团队 (lead + workers) |
| 工具权限 | 统一五层沙盒 | 类型化工具集 (explore/plan/code/test) |
| 进程模型 | 单进程 agent loop | subprocess.Popen 独立进程 |
| 消息传递 | 无 (单 agent) | JSONL inbox + drain 模式 |
| 执行模式 | 无 (单 agent) | 前台 (blocking) / 后台 (parallel) |
| 生命周期 | 无 | create -> spawn -> coordinate -> delete |
| 故障隔离 | 进程崩 = 全死 | worker 崩 = 只影响该 worker |
| 任务追踪 | 无 | 文件系统 task board |

## 试一试

```sh
cd learn-claude-code
python agents/s15_production_teams.py
```

试试这些 prompt (英文 prompt 对 LLM 效果更好, 也可以用中文):

1. `Create a team called "refactor" and spawn an explore agent to analyze the codebase structure` -- 创建团队 + 前台 explore agent
2. `Spawn a background code agent to fix the README and a background test agent to run the tests` -- 两个后台 agent 并行工作
3. `List the team and check task status` -- 查看团队成员和任务进度
4. `Send a message to the code agent: "Also update the CHANGELOG"` -- 用 SendMessage 继续 agent 的 session
5. `Delete the team` -- 优雅关闭所有 worker 进程
