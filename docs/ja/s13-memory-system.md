# s13: Memory System [PLUS]

`s01 > s02 > s03 > s04 > s05 > s06 | s07 > s08 > s09 > s10 > s11 > s12 | [ s13 ]`

> *"セッションを超えて生き残る知識こそ、エージェントが成長している証拠"* -- メモリとは、時間を超えたコンテキストエンジニアリングである。
>
> **Harness 層**: 永続メモリ -- エージェントと自身の過去を繋ぐ最初の接点。

## 問題

すべてのセッションはゼロから始まる。エージェントはユーザーの好みを学び、プロジェクト構造を発見し、修正を受け取る。しかし会話が終わると、そのすべてが消える。次のセッションでは同じ間違い、同じ質問、同じ立ち上がり時間。コンテキストウィンドウは強力だが揮発性だ -- 1回の会話の間しか存在しない。

本物のアシスタントは覚えている。名前を二度聞かない。修正された後に同じ間違いを繰り返さない。足りないのは: セッションをまたいで知識を生き残らせる永続化レイヤーだ。

## 解決策

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

インデックスはシステムプロンプトに常駐。詳細はオンデマンドで読み込む。
エージェントは学んだことを覚えている -- 何セッションにもわたって。
```

2層設計: コンパクトな**インデックス**（常にシステムプロンプト内、200行以下）がエージェントに既知の全知識の概要を与え、**詳細ファイル**はツール経由でオンデマンドにロードされる。コンテキストウィンドウをスリムに保ちながら、完全な知識にアクセスできる。

### 他システムのメモリ手法

| システム | アプローチ | トレードオフ |
|----------|-----------|-------------|
| **Claude Code** (CLAUDE.md / MEMORY.md) | Markdownファイルをシステムプロンプトに注入 | 手動、プロジェクトスコープ、構造化メタデータなし |
| **Anthropic Memory Tool API** | サーバーサイドのKey-Valueストア（ツール呼び出し経由） | プラットフォーム管理、不透明なストレージ、API依存 |
| **ChatGPT** | 隠れたメモリ要約をシステムプロンプトに追加 | 自動だがユーザーが構造を制御できない |
| **MemGPT / Letta** | メイン/アーカイブメモリ間のページングによる仮想コンテキスト | 最も柔軟だが複雑性も最大 |

我々のアプローチはベストアイデアを借用している: Claude Codeのようにファイルベース（検査可能、バージョン管理可能）、Anthropic Memory APIのようにツールアクセス（エージェント駆動）、frontmatterメタデータで構造化（検索可能、型付き）、MemGPTのように2層（インデックス + 詳細）。

## 仕組み

1. **MemoryManagerを初期化する。** `.memory/`ディレクトリを作成し、空のインデックスを生成する。

```python
class MemoryManager:
    VALID_TYPES = {"user", "feedback", "project", "reference"}

    def __init__(self, memory_dir: Path):
        self.dir = memory_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("# Memory\n\n(empty)\n")
```

ディレクトリ構造:

```
.memory/
├── MEMORY.md           # インデックス: 常にシステムプロンプト内（<200行）
├── user_prefs.md       # 詳細: memory_readツールでロード
├── project_auth.md
└── feedback_testing.md
```

2. **frontmatterを解析して構造化メタデータを得る。** 各詳細ファイルはYAML風のヘッダーを持ち、それをもとにインデックスが構築される。

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

詳細ファイルの例:

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

3. **frontmatter付きでメモリを書き込む。** エージェントが覚えておく価値のあることを学んだとき、構造化メタデータ付きのファイルを保存する。

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

4. **インデックスを自動的に再構築する。** 書き込み、更新、削除のたびにインデックスが再構築される。インデックスはファイルをタイプ別にグループ化し、1行の説明を添える -- エージェントが瞬時にスキャンできる目次だ。

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

生成されるインデックスの例:

```markdown
# Memory

## User
- [User Preferences](user_prefs.md) - Editor settings and communication style

## Project
- [Auth Refactor](project_auth.md) - Backend auth migration status

## Feedback
- [Testing Conventions](feedback_testing.md) - Always run pytest before committing
```

5. **インデックスをシステムプロンプトに注入する。** エージェントは毎セッション、自分が何を知っているかを既に知った状態で始まる。

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

6. **5つのツールがエージェントに完全なCRUD制御を与える。** エージェント自身が何を覚え、いつ参照し、いつ忘れるかを決定する。

| ツール | 用途 |
|--------|------|
| `memory_view` | インデックスの表示またはメタデータ付きファイル一覧 |
| `memory_read` | 特定の詳細ファイルをコンテキストにロード |
| `memory_write` | メモリファイルの作成または上書き |
| `memory_update` | 既存ファイル内のテキストを部分更新（str_replace） |
| `memory_delete` | 不要になったファイルを削除 |

エージェントループ自体はs01から変わらない -- ツールとシステムプロンプトだけが異なる。メモリはエージェントが呼び出せるもう1つのツールに過ぎない。

## s12からの変更点

| コンポーネント     | 以前 (s12)                          | 以後 (s13)                                         |
|--------------------|------------------------------------|-----------------------------------------------------|
| 永続化             | タスク/worktree状態をディスクに保存 | + 汎用知識もディスクに保存                          |
| セッション開始時   | 白紙状態                            | インデックスをシステムプロンプトにプリロード        |
| 知識の蓄積         | なし                                | エージェント駆動で`memory_write`により保存          |
| 整理方法           | フラットなタスクJSON                | 型付きfrontmatter (user/feedback/project/reference) |
| コンテキストコスト | N/A                                 | インデックスのみ; 詳細はオンデマンドでロード        |

## 試してみる

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
