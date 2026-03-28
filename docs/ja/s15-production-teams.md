# s15: プロダクションエージェントチーム [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | s13 > s14 > [ s15 ]`

> *"同じパターン、本物のプロセス -- スレッドはシミュレート、プロセスは隔離する"* -- プロダクションチームは利便性とクラッシュ安全性を交換する。
>
> **Harness 層**: プロダクションチーム -- 型付き能力によるプロセスベースのエージェント連携。

## 問題

s09からs12にかけて、完全なチーム連携システムを構築した -- 役割、プロトコル、自律ループ、worktree分離。しかし、本番環境では通用しない3つの簡略化があった:

1. **プロセスではなくスレッド。** すべてのエージェントが1つのPythonインタプリタを共有する。1つのエージェントがクラッシュするとチーム全体がダウンする。1つのエージェントの無限ループが全員をフリーズさせる。OSレベルの隔離がない。

2. **均一なツールアクセス。** すべてのエージェントが同じツールを持つ。ファイルの読み取りだけをすべき「リサーチャー」エージェントが、書き込みやシェルコマンドの実行もできてしまう。最小権限の原則が適用されていない。

3. **フォアグラウンド/バックグラウンドの区別なし。** すべてのエージェントがバックグラウンドスレッドで同時に実行される。リードは「このエージェントの結果を待ってから続ける」と「このエージェントが動いている間に先に進む」を区別できない。実行モードの制御がない。

これらの簡略化は連携パターンの学習には十分だった。しかし実際のコードベースに対してエージェントを実行するには不十分だ。

## 解決策

```
リードプロセス (PID 1000)             ワーカープロセス (PID 1001)
┌──────────────────────┐              ┌──────────────────────┐
│ agent loop           │              │ agent loop           │
│ tools: ALL + team    │   Popen()    │ tools: 型ごと        │
│ context: own msgs[]  │─────────────>│ context: own msgs[]  │
│                      │              │                      │
│ drain_completions()  │<─ ─ ─ ─ ─ ─ │ send_message("lead") │
└──────────────────────┘   result     └──────────────────────┘
          │                                    │
          v          共有ファイルシステム         v
┌─────────────────────────────────────────────────┐
│ .s15_teams/{name}/                              │
│   config.json     <- チーム構成 + 型            │
│   inbox/          <- メッセージ配信 (JSONL)     │
│   results/        <- ワーカー出力ファイル       │
│   tasks/          <- タスクボード               │
└─────────────────────────────────────────────────┘
```

スレッドをOSプロセスに置き換える。各ワーカーは独立した`python s15_worker.py`呼び出しで、独自のインタプリタ、独自のAPI接続、独自の`messages[]`を持つ。通信はファイルシステム経由 -- JSONLインボックスと結果ファイル。クラッシュしたワーカーは非ゼロコードで終了し、リードは動き続ける。

## 仕組み

1. **型レジストリがエージェントごとのツールを制限。** 各エージェント型は許可されたツールセットにマッピングされる。レジストリはスポーン時に最小権限を強制する -- ワーカーは使うべきでないツール定義を最初から受け取らない。

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

| 型 | 読み取り | 書き込み | 実行 | ユースケース |
|----|----------|----------|------|-------------|
| **explore** | 可 | 不可 | 不可 | リサーチ、コード分析 |
| **plan** | 可 | 不可 | 不可 | アーキテクチャ設計 |
| **code** | 可 | 可 | 可 | 実装 |
| **test** | 可 | 不可 | 可 | テスト実行、検証 |

2. **ワーカーは実際のサブプロセスとしてスポーン。** `subprocess.Popen`が各ワーカーを独立したOSプロセスとして起動する。各ワーカーは独自のPythonインタプリタ、独自のLLM API接続、独自のコンテキストウィンドウを持つ。

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

3. **フォアグラウンド vs バックグラウンド実行。** リードはスポーン時に選択する。フォアグラウンドエージェントは完了までリードをブロックする -- 結果がすぐに必要な逐次作業に適している。バックグラウンドエージェントはリードに制御を返す -- 並列作業に適している。

```python
    if not background:
        # フォアグラウンド: ワーカー完了まで待機
        proc.wait()
        result = self._read_result(name)
        return f"[{name} completed]\n{result}"
    else:
        # バックグラウンド: 即座に返る
        return f"Agent '{name}' spawned in background (PID {proc.pid})"
```

4. **JSONLインボックスによるファイルベースのメッセージング。** 各エージェントは`.s15_teams/{team}/inbox/{name}.jsonl`にインボックスファイルを持つ。メッセージはJSON行として追記される。読み取りはインボックスを排出する（read-then-clearパターン）。共有メモリ、ロック、競合状態を回避する。

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
        self.file.write_text("")  # 読み取り後に排出
        return messages

    def send(self, to: str, content: str, from_name: str) -> str:
        target = self.inbox_dir / f"{to}.jsonl"
        msg = {"from": from_name, "content": content, "ts": time.time()}
        with open(target, "a") as f:
            f.write(json.dumps(msg) + "\n")
```

5. **ワーカーは`send_message`で結果を報告。** 読み取り専用のexploreエージェントを含むすべてのエージェント型が`send_message`ツールを持つ。ワーカーは完了時にインボックス経由で最終結果を`lead`に送信する。リードの`drain_completions()`が各LLMターン前にこれらを収集する。

```python
# ワーカーの最終アクション: リードに通知
inbox.send("lead", f"[{args.name} completed] {final[:500]}", args.name)

# リードは各ターン前に排出
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

6. **ライフサイクル: 作成、スポーン、連携、削除。** チームには明示的なライフサイクル管理がある。`delete_team`はすべてのアクティブワーカーに`__shutdown__`を送り、正常終了を待ち、10秒のタイムアウト後に残存プロセスを強制終了する。

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

## 比較: s09-s12 vs s15 / Claude Code

| 次元 | s09-s12（スレッドチーム） | s15（プロセスチーム） | Claude Code |
|------|--------------------------|----------------------|-------------|
| **隔離** | 1プロセス内のスレッド | 個別のOSプロセス | 個別のプロセス |
| **クラッシュ動作** | 1つのクラッシュで全滅 | ワーカー終了、リード継続 | ワーカー終了、リード継続 |
| **ツールアクセス** | 均一（全ツール） | 型付き（エージェント型ごと） | 型付き（Explore/Plan/Code） |
| **実行モード** | バックグラウンドのみ | フォアグラウンド + バックグラウンド | フォアグラウンド + バックグラウンド |
| **通信** | Python共有辞書 | ファイルシステムJSONLインボックス | 内部メッセージバス |
| **コンテキストウィンドウ** | 共有またはフォーク | 完全に独立 | 完全に独立 |
| **ライフサイクル** | 暗黙的（thread join） | 明示的（create/spawn/delete） | 明示的（TeamCreate/TeamDelete） |
| **連携** | Pythonロック/イベント | ファイルベース + プロセスシグナル | SendMessage + drain |

## Claude Code 実際の使い方

Claude Codeのマルチエージェントシステムはs15のパターンに直接対応する:

| Claude Code | s15の対応 | 説明 |
|------------|-----------|------|
| `TeamCreate` | `create_team()` | チームワークスペースの初期化 |
| `Agent(type=Explore)` | `spawn_agent(type="explore")` | 読み取り専用のリサーチエージェント |
| `Agent(type=Plan)` | `spawn_agent(type="plan")` | 計画エージェント、編集なし |
| `Agent()`（汎用） | `spawn_agent(type="code")` | フル機能エージェント |
| `Agent(background=true)` | `spawn_agent(background=True)` | ノンブロッキングの並列作業 |
| `SendMessage` | `send_message()` | エージェント間通信 |
| `TeamDelete` | `delete_team()` | チームの解散 |
| 各ターンでのdrain | `drain_completions()` | バックグラウンド結果の収集 |

重要な洞察: Claude CodeのAgentツールは現在のプロセス内でスレッドをスポーンしない。個別のClaude Codeプロセスを起動する -- 各々が独自のコンテキスト、独自のツールセット、独自のサンドボックスを持つ。s15はこのアーキテクチャを`subprocess.Popen`とファイルベースのメッセージングで再現している。

## s14からの変更点

| コンポーネント | 以前 (s14) | 以後 (s15) |
|---------------|-----------|-----------|
| 焦点 | セキュリティ（サンドボックス + 権限） | マルチエージェント連携 |
| エージェントモデル | 多層セキュリティの単一エージェント | リード + 型付きワーカープロセス |
| プロセスモデル | 1プロセス | Popenによる複数OSプロセス |
| ツールアクセス | deny/ask/allowによる均一アクセス | 型ごとのツール制限 |
| 通信 | N/A（単一エージェント） | JSONLインボックス + 結果ファイル |
| 実行モード | N/A | フォアグラウンド（ブロッキング）+ バックグラウンド（並列） |
| ライフサイクル | N/A | create_team / spawn / delete_team |
| タスク追跡 | N/A | ファイルベースのタスクボード |

## 試してみる

```sh
cd learn-claude-code
python agents/s15_production_teams.py
```

1. `Create a team called "demo" for exploring this project.`
2. `Spawn an explore agent named "scanner" to list all Python files.`（フォアグラウンド、読み取り専用）
3. `Spawn a background explore agent named "reviewer" to analyze the agent loop in s01.`
4. `List the team to see agent statuses.`
5. `Send a message to reviewer asking for a summary.`
6. `Create a task "Write unit tests" and assign it to a test agent.`
7. `Delete the team when done.`
