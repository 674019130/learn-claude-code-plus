# s14: Sandbox & Permissions [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | s13 > [ s14 ]`

> *"エージェントに力を与えよ、しかし越えてはならない線を引け"* -- サンドボックスとは安全な自律性の技術である。
>
> **Harness 層**: サンドボックスと権限 -- エージェントとOSの間にある5つの防壁。

## 問題

シェルアクセスを持つ無防備なエージェントは装填済みの銃だ。`rm -rf /`を実行し、`curl`でデータを外部送信し、`.env`の秘密鍵を読み取り、プロンプトインジェクションに騙されて任意のコマンドを実行しうる。OWASP Top 10 for LLM Applicationsは「安全でないプラグイン設計」と「過剰な権限」を重大な脅威として挙げている -- どちらもツールアクセスを持つコーディングエージェントに直接当てはまる。

課題: エージェントは有用であるために*本物の力*（ファイルI/O、シェル、ネットワーク）が必要だ。しかし、すべてのツール呼び出しは潜在的な攻撃面である。エージェントに自律性を与えつつ、王国の鍵は渡さないようにするにはどうすればよいか?

## 解決策

```
LLMからのツール呼び出し
        |
        v
┌───────────────────┐
│ L1: Path Sandbox   │  resolve() + is_relative_to()
└────────┬──────────┘
         v
┌───────────────────┐
│ L2: Resource Limit │  タイムアウト120秒、出力50K
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
    ツールを実行

多層防御: 各レイヤーが前のレイヤーの漏れを補う。
単一レイヤーでは不十分。5つが揃って安全な自律性が実現する。
```

5つのレイヤーが、すべてのツール呼び出しで上から下へ評価される。各レイヤーは独立して実行をブロックできる。全レイヤーを通過した場合のみツールが実行される。これは多層防御 -- Webセキュリティにおけるファイアウォール、認証、入力検証と同じ原則だ。

## 仕組み

1. **`safe_path`によるパスサンドボックス。** すべてのファイル操作でパスを解決し、ワークスペース内に収まることを確認する。ディレクトリトラバーサル（`../../etc/passwd`）やシンボリックリンク脱出を防ぐ。

```python
def safe_path(p: str) -> Path:
    """パスを解決しワークスペース内であることを検証。
    防御: ディレクトリトラバーサル、シンボリックリンク脱出。
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

2. **すべてのコマンドにリソース制限。** シェルコマンドには120秒のタイムアウトと出力50K文字の上限がある。暴走プロセスや出力フラッディングを防ぐ。

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

3. **OSレベルのサンドボックス。** 本番環境では、エージェントプロセスはカーネルレベルでシステムコールを制限するOSサンドボックス内で実行される。最も突破困難なレイヤー -- L1-4を回避しても、OS自体が危険な操作をブロックする。

| 製品 | 技術 | メカニズム |
|------|------|-----------|
| **Claude Code** | macOS Seatbelt | ネットワークブロック、ファイルシステムをワークスペースに制限 |
| **Cursor** | Seatbelt + Landlock + seccomp | 3層のOS強制 |
| **OpenAI Codex** | K8s上のgVisor | ユーザー空間カーネル、完全なネットワーク遮断 |

4. **deny/ask/allowルールによるPermissionManager。** ルールは順序通りに評価: deny（常にブロック）、ask（ユーザーに確認）、allow（自動許可）。最初にマッチしたルールが適用。デフォルト: deny。

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
        """deny -> ask -> allow の順で評価。最初のマッチが勝つ。"""
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

5. **ライフサイクル制御のためのフック。** PreToolUseフックは権限チェックの前に実行され、オーバーライドできる。PostToolUseフックは実行後にログやAuditを行う。Claude Codeでは、フックは`settings.json`のシェルコマンドとして設定される。

```python
class HookManager:
    def run_pre(self, tool_name: str, args: dict) -> tuple[str | None, str]:
        for name, fn in self.pre_hooks:
            decision = fn(tool_name, args)
            if decision is not None:
                return decision, f"hook '{name}'"
        return None, ""

# 例: データ窃取をブロック
def _block_pipe_to_curl(tool_name, args):
    if tool_name == "bash" and "| curl" in args.get("command", ""):
        return "deny"
    return None

HOOKS.register_pre("block-exfiltration", _block_pipe_to_curl)
```

6. **6つの権限モードで信頼レベルを制御。** Claude Codeは最大安全から完全自律までのスペクトルを提供する:

| モード | 動作 | ユースケース |
|--------|------|-------------|
| **Default** | 書き込み/実行時にプロンプト、読み取りは許可 | 通常の開発 |
| **Plan mode** | 読み取り専用、書き込みや実行なし | コードレビュー、探索 |
| **allowedTools** | 特定ツールのホワイトリスト | CI/CDパイプライン |
| **dangerouslySkipPermissions** | プロンプトなし | 信頼された自動化（100%自律） |

## 比較: 各製品のサンドボックス実装

| 観点 | 本教材エージェント | Claude Code | Cursor | OpenAI Codex |
|------|-------------------|-------------|--------|------------|
| **パスサンドボックス** | Python `resolve()` | `safe_path` + ルール | ワークスペース制限 | コンテナファイルシステム |
| **リソース制限** | 120秒タイムアウト、50K上限 | タイムアウト + 切り詰め | 設定可能な制限 | コンテナリソース |
| **OSサンドボックス** | なし（デモ） | Seatbelt (macOS) / seccomp (Linux) | Seatbelt + Landlock + seccomp | gVisorユーザー空間カーネル |
| **権限システム** | deny/ask/allowルール | deny/ask/allow + 6モード | ワークスペース + 管理者ポリシー | 暗黙的deny-all |
| **フック** | Pythonコールバック | settings.jsonのシェルコマンド | N/A | N/A |
| **プロンプト削減** | N/A | 権限プロンプトを**84%**削減 | 中断を**40%**削減 | **100%**（プロンプトなし -- 完全サンドボックス） |

重要な洞察: OSサンドボックスが強力であるほど、権限プロンプトは少なくなる。OpenAIのgVisorアプローチはコンテナ自体が権限システムなのでプロンプトがゼロ。Claude CodeのSeatbeltは安全な操作が多いため84%削減。Cursorのアプローチは中断を40%削減。

### Anthropicのエージェント安全5原則

1. **行動前に考える** -- ツール呼び出し前にchain-of-thoughtを使用
2. **最小限のフットプリントで動作** -- 必要な権限のみ要求
3. **不確実な場合は助けを求める** -- 確信が低い場合は人間にエスカレーション
4. **行動前に情報を検証** -- 信頼できない入力を信用しない
5. **可能な限りサンドボックス化** -- デフォルトで制限された環境で実行

## s13からの変更点

| コンポーネント | 以前 (s13) | 以後 (s14) |
|---------------|-----------|-----------|
| セキュリティモデル | なし（信頼された環境） | 5層サンドボックス |
| ファイルアクセス | 直接 `Path.read_text()` | `safe_path()`でワークスペース検証 |
| シェル実行 | 制限なし | 120秒タイムアウト、50K出力上限 |
| 権限制御 | なし | deny/ask/allowルールエンジン |
| ライフサイクルフック | なし | PreToolUse/PostToolUse |
| ツール信頼性 | 全ツール均等に信頼 | リスクレベル別にツールを分類 |

## 試してみる

```sh
cd learn-claude-code
python agents/s14_sandbox_permissions.py
```

1. `List the current permission rules.`
2. `Try to read the .env file.`（拒否されるはず）
3. `Try to run: rm -rf /`（拒否されるはず）
4. `Read a normal file in the workspace.`（許可されるはず）
5. `Run: echo hello world`（askルールを通過するはず）
6. `Add a deny rule for Bash(curl *)` then try `Run: curl example.com`
7. `Check which rules apply to the bash tool.`
