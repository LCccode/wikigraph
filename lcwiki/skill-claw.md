---
name: lcwiki
description: Enterprise knowledge base - compile documents into structured Wiki + knowledge graph + Q&A
trigger: /lcwiki
---

# /lcwiki

> **📌 OpenClaw 平台专属说明（阅读此 skill 的 LLM 请遵循）**
>
> 1. **默认 KB 路径** = `~/.openclaw/lcwiki/`（`install --platform claw` 时自动创建）。当用户执行 `/lcwiki xxx` 不带 `kb_path` 参数时，**一律使用这个默认路径**。
> 2. **Subagent 派发（并发优先，顺序兜底）**：OpenClaw **支持** subagent，大批量文件（>5）时必须派发。派发模式：
>    - **优先**：在一条消息里同时派发多个 subagent 尝试并发（如果平台能真并发，速度最快）
>    - **兜底**：若平台不支持并发、一次只跑一个，就顺序派——前一个 subagent 完成后再派下一个。**比主 agent 自己顺序处理好**的是：每个 subagent 有独立 context，主 agent 只做调度不累积压力
>    - 严禁"主 agent 自己处理所有文件"—— 除非文件数 ≤3，否则必须通过 subagent
> 3. **AGENTS.md 集成**：`lcwiki install --platform claw` 会在当前目录的 `AGENTS.md` 追加"本项目使用 lcwiki（默认 KB 在 `~/.openclaw/lcwiki/`）"说明。
>
> 其余规则与 Claude Code 完全一致。

将用户上传的文件（Word/PDF/Excel/PPT/图片/音视频）编译成结构化 Wiki 知识库 + 知识图谱，支持精准问答和知识库自愈。

## Usage

```
/lcwiki ingest [kb_path]                  # 处理 raw/inbox/ 中的文件
/lcwiki compile [kb_path] [--deep]        # 编译 Wiki
/lcwiki graph [kb_path]                   # 更新图谱
/lcwiki audit [kb_path]                   # 图谱体检（LLM 判断幽灵节点等）
/lcwiki query [kb_path] "问题"            # 知识问答
/lcwiki update [kb_path] <filename>       # 替换已入库的旧文件（清旧版再 ingest 新版）
/lcwiki status [kb_path]                  # 知识库状态
```

kb_path 是知识库根目录（包含 raw/ vault/ staging/ 的目录）。如果用户未指定，从对话上下文推断。

## Honesty Rules

- Never invent an edge. If unsure, use AMBIGUOUS.
- Never skip warnings. Always show token cost. Show raw numbers.
- Backup graph.json before any change.

## Execution Bounds (READ FIRST — applies to EVERY subcommand)

These rules protect knowledge-base integrity. Violating any one produces a corrupted KB that looks plausible but is unreliable. A **failure is always recoverable; a forgery is not**. When in doubt, stop and report.

1. **The CLI owns deterministic work. You own semantic judgment.** Tasks like building/clustering/analyzing the graph, generating HTML / reports / nav pages, exporting Obsidian vaults — these are deterministic Python, called via `lcwiki graph-run` / `lcwiki graph-verify`. You **MUST NOT** reimplement them in Python heredocs, `networkx` scripts, or hand-written Write-tool files. Your work is LLM-native: reading documents, extracting concepts/relations, judging confidence, answering questions.

2. **If you cannot execute Bash/Python, STOP.** Do not "degrade to hand-crafting" — that has produced forged `graph.json`, forged `index.html`, and nav pages with garbage filenames like `![img-003](assets_images_img-003.png).md` in past runs. Instead, reply to the user verbatim: *"I cannot execute the required Python environment (`lcwiki` CLI). /lcwiki commands that require computation (`graph`, `audit`) cannot run here. Please switch to a platform with Bash + Python + the `lcwiki` package installed."*

3. **Product file-name whitelist.** Only these files may exist directly under `<kb>/vault/graph/`: `graph.json`, `graph.html`, `graph_index.json`, `GRAPH_REPORT_SUMMARY.md`, `GRAPH_REPORT_FULL.md`. Only these subdirs: `cache/`, `obsidian/`. **Forbidden** to write anything else (e.g. `index.html`, `.graph_llm_<timestamp>.json`, `.index_llm_<timestamp>.html`, `my_notes.txt`). If the CLI doesn't produce a file, you don't create it.

4. **Under `<kb>/vault/wiki/nav/`, only `index.md` + `community-*.md` + `god-*.md` are allowed.** Any other filename is a forgery signal — delete and rerun `lcwiki graph-run`.

5. **`graph-verify` output is ground truth.** After `graph-run`, always run `lcwiki graph-verify --kb KB`. If it returns FAILED, surface every error line **verbatim** to the user. Do NOT try to fix it by writing files manually — the only legitimate fix path is "rerun Step 2 extraction with higher quality, then rerun graph-run".

6. **Never silently succeed.** If any step reports a warning / partial / error, include it in your user-facing summary. Hiding `schema_issues_post: 47` so the report "looks clean" is worse than telling the user the graph is partial.

## What You Must Do When Invoked

1. Parse the subcommand and kb_path from user input
2. Run Step 0 to verify lcwiki is installed
3. Execute the matching subcommand section below

---

## Step 0 — Verify installation

Run this bash command. If it fails, tell user `lcwiki` CLI is not installed or not on PATH, and STOP — do not try to "work around" by writing files manually.

```bash
lcwiki version || { echo "FATAL: lcwiki CLI not found on PATH. Run server-install.sh on the host."; exit 1; }
```

**Why CLI not `python3 -c "import lcwiki"`**: on some hosts (e.g. OpenClaw servers) the default `python3` on agent PATH is a system python without lcwiki installed — the CLI wrapper at `/usr/local/bin/lcwiki` always forwards to the correct Python interpreter.

---

## /lcwiki ingest [kb_path]

**智能入库**：扫 `<kb_path>/raw/inbox/` 下所有文件，自动分三类处理：

- ✨ **新增**（sha 未见过 + 文件名未见过）：标准 ingest → 转 content.md → 建 staging task
- 🔄 **更新**（同文件名但 sha 不同 — 用户改过的旧文件）：**自动**把旧版 article / archive dir / staging task / source_map entry 软删到 `.trash/`，然后把新版 ingest
- ⏭️  **跳过**（sha 已在 source_map 且 article 已 compile）：直接从 inbox 删除，不浪费 compile token

用户不用先 `/lcwiki update` 清旧版 — ingest 自己决策。

### Execution (ATOMIC)

⚠️ **One CLI call. DO NOT reimplement in Python; DO NOT hand-write files to `raw/archive/` or `staging/`. If the CLI fails, STOP — do not paper over by writing files manually.**

```bash
lcwiki ingest-run --kb KB_PATH
# Optional: --no-auto-update   (don't auto-clean old versions on filename match)

# Verify — MUST pass before running compile
lcwiki ingest-verify --kb KB_PATH
```

For OpenClaw default KB, use `KB_PATH=~/.openclaw/lcwiki`.

If `ingest-verify` reports FAILED, surface every error line **verbatim** to the user. The only legitimate fix is to re-run `ingest-run` after placing files in `raw/inbox/`.

### 用户场景对照

| 用户行为 | ingest 自动做什么 |
|---------|-----------------|
| 上传**全新**文件到 inbox | `new` 分类 → 正常 ingest → 建 task |
| 上传**内容改过**的旧文件（同文件名） | `updated` 分类 → 自动清旧版到 `.trash/` + ingest 新版 → 建 task（下次 compile 重编译）|
| 误传**已处理**的相同文件（sha 匹配） | `skipped` 分类 → 从 inbox 删，不建 task，不浪费 token |
| 上传**损坏/空/不支持**的文件 | `failed` 分类 → 留在 inbox 等排查 |

### 如果用户不想自动清旧版

`auto_update=False` 让 ingest **不碰旧记录**（新的"改过文件"会和旧版并存 — 不推荐）。或者让用户用旧的手动 `/lcwiki update <pattern>` 命令单独清理。

After running, report the results to the user.

---

## /lcwiki compile [kb_path] [--deep]

Compile pending tasks: LLM reads content.md → produces article + concepts.

Each file is read and understood by LLM for quality assurance.
Platform-specific dispatch: Claude Code uses parallel subagents; OpenClaw processes sequentially.

### Step 1 — Prepare task list, snapshot concepts, and content paths (ATOMIC)

⚠️ **One CLI call. DO NOT reimplement in Python.**

```bash
lcwiki compile-prepare --kb KB_PATH
```

Outputs:
- `/tmp/.lcwiki_compile_tasks.json` — the list of tasks you (the LLM) must iterate through
- `/tmp/.lcwiki_concepts_snapshot.json` — pre-compile concepts snapshot, used by compile-write for risk assessment (do not edit)

Read `/tmp/.lcwiki_compile_tasks.json` — it's a JSON array of `{task_id, sha256, content_path, name}` entries. This is your work list for Step 2.

### Step 2 — Dispatch compilation (platform-specific)

**Claude Code platform:** Use Agent tool for parallel dispatch.

Split files into chunks of ≤20. Dispatch ALL chunks in a SINGLE message using the Agent tool.
Each subagent_type MUST be "general-purpose" (needs Write access).

Each subagent receives this prompt (substitute CHUNK_FILES and KB_PATH):

```
You are a lcwiki compile subagent. Read the content.md files listed below and compile each into a structured wiki article.

KB path: KB_PATH
Files to compile:
CHUNK_FILES

For EACH file:
1. Read the content.md using the Read tool
2. Also check if assets/images/ directory exists next to content.md — if it has images, read them to understand visual content
3. Produce a structured article with YAML frontmatter and sections

Article frontmatter schema (**核心必需** vs **领域可选**):

**Core REQUIRED** (any corpus, any domain):
```yaml
---
title: "清晰的标题（源文件语言）"
doc_type: "solution | manual | faq | step | report | policy | paper | note | ..."
source_sha256: "前 16 位"
concepts: ["概念1", "概念2", "概念3"]      # MINIMUM 3 MAXIMUM 8
tldr: "≤100 字超浓缩摘要：回答 WHO/WHAT/HOW/KPI。query 层会先读 tldr 再决定是否全读 article（节省 token）"
created_at: "YYYY-MM-DD"
compiled_by: "claude-opus-4-7"
confidence: 0.XX
---
```

**`tldr` 字段是新增的 token 优化手段** —— query 时先扫所有 article 的 frontmatter.tldr（~100 字/篇），若答案足够就不必读全文；若 tldr 不够则按需读全文。目标：减少 50% query 阶段 token。

**Domain OPTIONAL** (仅在能从原文推断出来时填；没对应内容的领域**不要瞎编**):

- **业务方案类**: `domain` / `topic` / `region` / `customer` / `customer_type`
- **研究论文类**: `authors` / `venue` / `year` / `doi`
- **代码/技术类**: `platform` / `language` / `version`
- **政策类**: `jurisdiction` / `effective_date`

Validator 只强制 Core 字段；可选字段**存在即被节点继承**、query 层能按 `--filter` 检索。如果 content.md 是一篇论文而不是业务方案，写 `authors/year/venue` 而不是强塞 `region/customer`。

Article body sections (for doc_type=solution):
- 项目背景（政策依据、客户痛点）
- 核心需求（逐条列出）
- 解决方案（整体架构）
- 关键模块（表格：模块/功能/备注）
- KPI 与指标（量化数据）
- 报价结构（如有）
- 时间线（如有）
- 关联概念（[[双链]]引用）
- 来源（原文件名 + sha256）

Rules (MUST follow):
- **Frontmatter is MANDATORY**: `article_content` MUST start with `---\n<yaml>\n---\n# Title`. The yaml block MUST contain all required fields (title, doc_type, source_sha256, concepts, compiled_by, confidence). A write-time validator will reject any content that does not begin with `---`. This is the most common mistake — write the yaml FIRST, then the body.
- **Preserve ALL information**: every table, every number, every list item, every paragraph from content.md must appear in the article. Do NOT summarize, compress, or omit. Restructure into sections but KEEP EVERY DATA POINT. The article should be 40-70% of content.md size, NOT 10%.
- **Tables MUST be copied verbatim**: if content.md has a pricing/module/timeline table, copy it into the article exactly. Do NOT summarize tables into prose.
- **Lists MUST be preserved**: if content.md has a bullet list of 10 items, the article must have all 10 items.
- **Do NOT invent information**: if a section has no data, write "原文未涉及"
- **Images**: if content.md contains `![img-xxx](assets/images/...)` references, use the Read tool to read each image file. Describe what the image shows and keep the `![]()` reference in the article.
- **Concepts**: MINIMUM 3 concepts per article, MAXIMUM 8. Zero concepts is NEVER acceptable. Re-read the document if you cannot identify 3+.
- **Aliases**: each concept MUST have 2-3 synonyms/aliases listed in the summary (language follows the source file).
- **concept_kind（每个 concept 必填）**: 从以下枚举选一个最贴切的：
  - `capability` — 能力 (如"precise-teaching"、"student-assessment")
  - `product` — 具体产品/系统 (如"Notion AI Blocks"、"Cursor Composer")
  - `module` — 模块/组件 (如"Admin Dashboard"、"Automated Grader")
  - `framework` — 架构/框架 (如"MVC Architecture"、"MVC")
  - `policy` — 政策/规范 (如"GDPR Compliance Charter"、"GDPR")
  - `metric` — 指标/参数 (如"KPI"、"literacy-score")
  - `role` — 角色 (如"user"、"admin")
  - `method` — 方法论 (如"Agile"、"TRIZ")
  - `other` — 都不贴切时用这个
  这个分类让 query 层能过滤（如"列出所有 capability 类概念"），也让 God Nodes 分析能排除 policy 类。
- **concept 页内容详实化**: concept 文件不是 stub。至少要有：
  1. `## 概要` 段（3-5 句定义）
  2. `## 关键特征 / 核心能力` 段（3-8 个要点）— **如果 article 里该概念有 KPI / 量化指标（如"准确率 95%"、"serving 220 users"、"budget $460K"），必须下沉到这一段，不能仅留在 article 里。Query Q4b 类问题会直接在 concept 页检索 KPI。**
  3. `## 在方案中的应用` 段（每个引用 article 链 `[[方案名]] § 章节` 并简述该方案如何实现）
  4. `## 相关概念` 段（列同义 / 上下位 / 并列概念 + 关系说明）
  目标 ≥ 200 字。Query 层和 wiki navigation 都依赖 concept 页的内容质量。
- **aliases 家族合并**: 创建新 concept 前**必须**先查 `concepts_index.json`，若发现同主题的已有概念（别名重叠 / 语义近似 / 上下位关系），**优先合并为一个 concept**（把新方案当作该概念的新"应用"加入），而不是建重复概念。典型错误示例：
  - ❌ 同时存在 `Wellbeing Platform` 和 `区域Wellbeing Platform平台`（后者是前者的一种实施形态）
  - ✅ 只留 `Wellbeing Platform`，把"区域级实施"写进其 `## 在方案中的应用` 段
  这通过 `lcwiki.index.match_related_concepts()` 自动辅助判断；WRITEEOF 脚本已内置此检查。
- **[[双链]]**: use `[[概念名]]` for all concept cross-references in article body
- **Confidence**: self-assess 0.0-1.0. Use 0.40 ONLY if source file is empty/unreadable.

Additionally, for each file, also produce these BACKFILL outputs (enriching ingest phase data):
- **key_terms**: 10-15 precise Chinese key terms from this document (e.g., "digital-learning-platform", "precise-teaching", "Admin Dashboard"). NOT random N-grams.
- **entities**: customer names, product names, specific school names mentioned
- **doc_type_reason**: one sentence explaining why you chose this doc_type

After compiling each file, write the result through the atomic CLI (DO NOT write article / concept files directly with the Write tool — `compile-write` is the only sanctioned way):

**Per-task protocol:**

```bash
# 1. Save your generated article markdown to a temp file.
#    MUST start with ---\n<yaml frontmatter>\n---\n# Title
cat > /tmp/lcwiki_task_${TASK_ID}_article.md <<'ARTICLEEOF'
---
title: "...（源文件标题）"
doc_type: solution
source_sha256: "<前 16 位>"
concepts: ["概念1", "概念2", "概念3"]
tldr: "≤100 字超浓缩摘要：WHO/WHAT/HOW/KPI"
created_at: "2026-04-18"
compiled_by: "claude-opus-4-7"
confidence: 0.90
---

# 方案标题

## 项目背景
...

（请严格保留 40-70% 原文信息、所有表格 verbatim、所有列表条目）
ARTICLEEOF

# 2. Save the concepts list JSON (>= 3 concepts required).
cat > /tmp/lcwiki_task_${TASK_ID}_concepts.json <<'CONCEPTSEOF'
[
  {
    "name": "概念名",
    "aliases": ["别名1", "别名2"],
    "summary": "30-80 字一句话摘要",
    "domain": ["业务"],
    "concept_kind": "capability",
    "body_sections": {
      "概要": "3-5 句定义",
      "关键特征": "- 特征1\n- 特征2\n- 特征3",
      "在方案中的应用": "- [[方案标题]] § 章节：该方案如何落地（2-3 句）",
      "相关概念": "- [[同义概念]]：关系说明"
    }
  },
  { ... more concepts (total >= 3) ... }
]
CONCEPTSEOF

# 3. (Optional) save key_terms and entities for structure.json backfill.
cat > /tmp/lcwiki_task_${TASK_ID}_terms.json <<'TERMSEOF'
["precise-teaching", "student-assessment", "digital-learning-platform", "..."]
TERMSEOF
cat > /tmp/lcwiki_task_${TASK_ID}_entities.json <<'ENTITIESEOF'
["Acme Corp", "Notion AI Blocks", "..."]
ENTITIESEOF

# 4. Commit into KB via the atomic CLI. `compile-write` will:
#    - validate article frontmatter (reject missing required fields)
#    - validate concepts list (reject if < 3 or missing concept_kind)
#    - build/update concept pages with 4-section body
#    - update concepts_index (family merge via aliases)
#    - move staging task pending→processing→done/review
#    - backfill source_map + structure.json
lcwiki compile-write \
  --kb KB_PATH \
  --task-id "$TASK_ID" \
  --sha256 "$SHA256" \
  --title "方案标题" \
  --article /tmp/lcwiki_task_${TASK_ID}_article.md \
  --concepts /tmp/lcwiki_task_${TASK_ID}_concepts.json \
  --confidence 0.90 \
  --key-terms /tmp/lcwiki_task_${TASK_ID}_terms.json \
  --entities /tmp/lcwiki_task_${TASK_ID}_entities.json
```

If `compile-write` exits non-zero with a frontmatter / concept validation error, **fix your temp files and retry** — do NOT bypass by writing to `vault/wiki/` directly.

Dispatch example for 37 files (2 chunks):
```
[Agent call 1: files 1-20, subagent_type="general-purpose", prompt with CHUNK_FILES=first 20 files]
[Agent call 2: files 21-37, subagent_type="general-purpose", prompt with CHUNK_FILES=remaining 17 files]
```
ALL Agent calls in ONE message for parallel execution.

---

**OpenClaw platform — subagent-based dispatch**

File-count dispatching rules:
- **N ≤ 3 files**: you (main agent) process them yourself sequentially, one at a time. No subagent needed.
- **N > 3 files**: **MUST** dispatch to subagents. Do NOT try to process all files in the main context — it will cause context degradation and regex-fallback behaviour.

Chunk sizing:
- Chunk size = **5-8 files per subagent** (smaller than Claude Code's 20 because OpenClaw subagent context budgets tend to be smaller).
- Number of chunks ≈ `ceil(N / 6)`.

Dispatch mode (try parallel, fall back to sequential):

1. **Preferred — parallel dispatch**: in ONE reply message, emit multiple subagent calls simultaneously. If OpenClaw runs them in parallel, you get the full speedup. If OpenClaw serialises them, you still get independent contexts per chunk.

2. **Fallback — sequential dispatch**: if parallel dispatch produces errors or one-at-a-time execution, accept it — send the next subagent only after the previous one reports `✓ done` via its status message.

Either way: `"[compile] Dispatching K subagents, each handling ~M files"`

Each subagent receives this prompt (substitute CHUNK_FILES = the JSON array of task objects this subagent should handle; KB_PATH = real kb path):

```
You are a lcwiki compile subagent. Process the files listed below.

KB path: KB_PATH
Files to compile (task_id + content_path pairs):
CHUNK_FILES

For EACH file:
1. Read content.md via Read tool. Also read assets/images/ if present.
2. Generate article markdown and concepts JSON obeying every rule in the parent skill:
   - article MUST start with --- yaml --- frontmatter (title/doc_type/source_sha256/concepts≥3/tldr/
     created_at/compiled_by/confidence)
   - article body preserves 40-70% of content.md, tables verbatim, lists complete
   - concepts list has ≥3 entries, each with concept_kind + body_sections 4 段
3. Write article + concepts to temp files:
     cat > /tmp/lcwiki_task_<task_id>_article.md <<'ARTICLEEOF' ... ARTICLEEOF
     cat > /tmp/lcwiki_task_<task_id>_concepts.json <<'CONCEPTSEOF' [...] CONCEPTSEOF
     (optional: _terms.json, _entities.json for backfill)
4. Call the atomic CLI to commit:
     lcwiki compile-write --kb KB_PATH --task-id <task_id> --sha256 <sha> \
       --title "<标题>" --article /tmp/lcwiki_task_<id>_article.md \
       --concepts /tmp/lcwiki_task_<id>_concepts.json --confidence 0.9 \
       [--key-terms /tmp/..._terms.json] [--entities /tmp/..._entities.json]
5. If compile-write returns non-zero, fix the temp file (fix frontmatter / concept schema) and retry
   — DO NOT give up, DO NOT write to vault/wiki/ directly with Write tool.
6. After finishing ALL files in this chunk, emit a final status line:
     "[subagent ok] chunk_id=<N> compiled=<K>/<N_total>"

Hard constraints (apply to every chunk):
- NEVER use Write tool to create files under vault/wiki/ — only `lcwiki compile-write` may write there.
- NEVER use python heredoc to bypass the CLI — the CLI is the ONLY legitimate path.
- If you encounter an unrecoverable error, emit "[subagent failed] chunk_id=<N> reason=<error>"
  and stop this chunk; do not produce fake files.
```

After all subagents finish, main agent verifies:

```bash
lcwiki compile-verify --kb KB_PATH
```

If verify FAILS, identify which articles/concepts are missing or malformed, re-dispatch a subagent to redo only those tasks (staging/pending will already have them back if compile-write exited non-zero).

### Step 3 — Verify all outputs (ATOMIC)

After all per-task `compile-write` calls are done, run:

```bash
lcwiki compile-verify --kb KB_PATH
```

Expected output: `✅ compile verification passed — all articles + concepts have required schema.`

If FAILED: surface every error line **verbatim** to the user. Do not hand-craft the missing article / concept files — the only legitimate fix is to rerun `compile-write` for the affected tasks with corrected temp files.

### Step 4 — Report

After all tasks are done:

```bash
python3 -c "
from pathlib import Path; from lcwiki.compile import list_tasks
kb = Path('KB_PATH')  # REPLACE
done = len(list_tasks(kb / 'staging', 'done'))
review = len(list_tasks(kb / 'staging', 'review'))
wiki = kb / 'vault' / 'wiki'
articles = len(list((wiki / 'articles').glob('*.md'))) if (wiki / 'articles').exists() else 0
concepts = len(list((wiki / 'concepts').glob('*.md'))) if (wiki / 'concepts').exists() else 0
print(f'✅ 编译完成：{articles} 篇 article / {concepts} 个 concept')
print(f'   自动发布：{done} 篇 / 进入审核：{review} 篇')
# Show log tail
import subprocess
subprocess.run(['tail', '-5', str(kb / 'logs' / 'compile.log')], capture_output=False)
"
```

---

## /lcwiki graph [kb_path] [--obsidian] [--obsidian-dir PATH]

### Optional: Obsidian vault export

`--obsidian` opt-in 生成 Obsidian vault（一节点一 `.md` 文件 + `graph.canvas` 画布）。用户要直接在 Obsidian / Logseq 里浏览 / 编辑图谱时使用。产出位置：
- 默认 `<kb>/vault/graph/obsidian/`
- `--obsidian-dir ~/vaults/my` 写入已有 vault

不带 `--obsidian` 时只产 `graph.json / graph.html / GRAPH_REPORT_*.md / nav/` 等标准产物。


Build knowledge graph from compiled wiki pages.

### Step 1 — Backup

```bash
cp KB_PATH/vault/graph/graph.json KB_PATH/vault/graph/.graph_backup_$(date +%s).json 2>/dev/null || true
```

### Step 2 — Read all wiki pages

Platform-specific dispatch: Claude Code uses parallel subagents; OpenClaw uses subagents too (parallel preferred, sequential fallback).

- **Claude Code**: split files into chunks of ≤25 and dispatch all chunks in a SINGLE Agent-tool message (`subagent_type="general-purpose"`). Each subagent writes `vault/graph/.extract_chunk_<ID>.json`. After all finish, read the chunks, merge by id, and feed into Step 3.

- **OpenClaw (subagent-based dispatch — REQUIRED for any KB with > 5 files)**:
  - Chunk size: **10-15 files per subagent** (a bit larger than compile because extraction is shallower per file). Number of subagents ≈ `ceil(N / 12)`.
  - Dispatch mode: try parallel first (emit all subagent calls in one message). If OpenClaw serialises, accept it — you still get independent contexts per chunk, which is much better than main-agent context carrying all N files.
  - Each subagent receives this prompt (substitute CHUNK_FILES, KB_PATH, CHUNK_ID):

    ```
    You are a lcwiki graph-extraction subagent. Read the wiki pages listed below
    and emit a partial extraction JSON.

    KB path: KB_PATH
    Chunk id: CHUNK_ID
    Wiki pages to extract (absolute paths to .md files under vault/wiki/articles/ and concepts/):
    CHUNK_FILES

    For each page, extract nodes / edges / hyperedges.

    === Node shape (ALL fields mandatory; NO omissions) ===

    For a concept node (file under vault/wiki/concepts/):
      {
        "id": "concept_xxx",
        "label": "中文名称（来自源文件 frontmatter.name 或首行 # 标题）",
        "file_type": "concept",
        "source_file": "concepts/<filename>.md",
        "concept_kind": "capability | product | module | framework | policy | metric | role | method | other"
      }

    For a document / solution node (file under vault/wiki/articles/):
      {
        "id": "solution_xxx",
        "label": "方案标题（来自源文件首行 # 标题）",
        "file_type": "document",
        "source_file": "articles/<filename>.md",
        "region": "...", "customer": "...", "customer_type": "..."   (optional attrs)
      }

    === source_file HARD RULES (violate → graph-run will reject / auto-heal) ===

    1. source_file MUST start with "concepts/" or "articles/" — NEVER omit the
       directory prefix. "大模型user助手.md" is WRONG; "concepts/大模型user助手.md"
       is correct.
    2. file_type and source_file directory MUST match:
         file_type="concept"  ⇔ source_file starts with "concepts/"
         file_type="document" ⇔ source_file starts with "articles/"
       If you feel a term "should be" a document but it's in concepts/ directory,
       it IS a concept — trust the directory, not your intuition.
    3. source_file MUST name a real .md file that exists in the KB. DO NOT invent
       filenames. If a concept is referenced in an article but no concepts/XXX.md
       exists, skip making a node for it (or reuse an existing concept whose label
       or alias matches).

    === Edge rules ===

    - relation ∈ {applied_to, references, includes_module, semantically_similar_to,
                   triggered_by, provides, uses, depends_on, part_of, example_of}
    - confidence_score REQUIRED: EXTRACTED=1.0, INFERRED=0.6-0.9, AMBIGUOUS=0.1-0.3
    - source and target MUST both exist in the nodes array of THIS chunk. Do NOT
      reference node ids from other chunks by guessing their id strings.

    === Cross-chunk semantic edges ===

    At least ⌈0.5 × N_in_chunk⌉ `semantically_similar_to` edges between nodes in
    different source_files of THIS chunk. If prior chunks' extract files exist
    (vault/graph/.extract_chunk_*.json), you may read their node ids+labels and
    add cross-chunk semantic edges — but only if you are certain the other chunk's
    id string. Otherwise keep your semantic edges within this chunk.

    === Hyperedges (≤3 per chunk) ===

    Shape: {"id": "hyper_xxx", "label": "...", "members": ["id1","id2","id3"],
            "member_count": 3, "grouping_criteria": {...}}
    Every member id MUST exist in the nodes array. "members" is plural.

    === Output ===

    Write to: vault/graph/.extract_chunk_<CHUNK_ID>.json
    Shape: {"nodes": [...], "edges": [...], "hyperedges": [...]}

    Then emit status: "[subagent ok] chunk_id=<CHUNK_ID> nodes=<N> edges=<E> hyperedges=<H>"

    === Hard constraints (break any one → chunk rejected) ===

    - NEVER write to vault/graph/graph.json, graph.html, or GRAPH_REPORT_*.
    - NEVER invent node ids that aren't backed by a real .md file.
    - NEVER omit source_file directory prefix.
    - NEVER create a node whose file_type conflicts with source_file directory.
    - If a wiki page is empty/malformed, skip it and log "skipped: <path> <reason>".
    ```

  - After all subagents finish, main agent merges chunks:
    ```bash
    /opt/anaconda3/bin/python3 <<'MERGE'
    import json, glob
    from pathlib import Path
    chunks = sorted(Path('/root/.openclaw/lcwiki/vault/graph').glob('.extract_chunk_*.json'))
    merged = {'nodes': [], 'edges': [], 'hyperedges': []}
    seen_node = set()
    for c in chunks:
        d = json.loads(c.read_text())
        for n in d.get('nodes', []):
            if n['id'] not in seen_node:
                seen_node.add(n['id'])
                merged['nodes'].append(n)
        merged['edges'].extend(d.get('edges', []))
        merged['hyperedges'].extend(d.get('hyperedges', []))
    Path('/tmp/lcwiki-extraction.json').write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(f"merged: {len(merged['nodes'])} nodes / {len(merged['edges'])} edges / {len(merged['hyperedges'])} hyperedges")
    MERGE
    ```
  - **Do NOT** attempt to emit one giant extraction JSON in a single LLM turn for > 5 files — it either (a) truncates output, or (b) degrades quality for later documents due to context pressure. Subagent dispatch is non-negotiable.

Read every .md file in `vault/wiki/articles/` and `vault/wiki/concepts/`. For EACH page, extract:

- **Nodes**: ONLY 2 types allowed:
  1. `solution` / `document` / `article` — one per article (file_type="document")
  2. `concept` — concepts described in concepts/*.md (file_type="concept")
- **Edges**: relationships between nodes (applied_to/references/includes_module/semantically_similar_to etc.)
- **Hyperedges**: 3+ nodes forming a group (≤3 per page). **Required shape** (every field mandatory):
  ```json
  {
    "id": "hyper_xxx",
    "label": "陕西公办学校智慧校园集群",
    "members": ["solution_xxx", "solution_yyy", "solution_zzz"],
    "member_count": 3,
    "grouping_criteria": {"customer_type": "公立", "region": "陕西"}
  }
  ```
  ⚠️ The members field is **`members`** (plural, not `nodes`). Without `id` or with `members` ≥2 the hyperedge will be rejected by schema validation. `grouping_criteria` is optional but recommended.

Rules:
- confidence_score REQUIRED on every edge: EXTRACTED=1.0, INFERRED=0.6-0.9, AMBIGUOUS=0.1-0.3
- NEVER use 0.5 as default
- **Every node object MUST contain ALL FIVE fields**: `id`, `label`, `file_type`, `source_file` (for concept nodes referencing a .md file), and any optional attributes. A node missing ANY of these fields will be rejected by schema validation. The ONLY valid node shape is:

  For concept nodes (copy `concept_kind` from the concept file's frontmatter — required):
  ```json
  {"id": "concept_xxx", "label": "中文名称（来自源文件）", "file_type": "concept", "source_file": "concepts/中文名称.md", "concept_kind": "capability"}
  ```
  `concept_kind` must be one of: `capability / product / module / framework / policy / metric / role / method / other`. Read it from the concept file's frontmatter; if the frontmatter lacks it, infer from context and tag `other`. Graph analysis (God Nodes / query filters) uses this to separate core abilities from policy references.
  For document/solution nodes:
  ```json
  {"id": "solution_xxx", "label": "方案标题（来自源文件首行 # 标题）", "file_type": "document", "source_file": "articles/方案标题.md", "region": "...", "customer": "...", "customer_type": "..."}
  ```

- **`label` MUST be the human-readable name from the source file** (Chinese 中文, English, or whatever the file uses). It MUST NOT equal the id, MUST NOT look id-like (no `concept_`, `solution_`, `xxx:yyy`, pinyin/romanisation). If you can only come up with an id, you haven't opened the file — go back and read the `# 标题` line.
- **`file_type` MUST be one of**: `concept` (for files under `concepts/`) or `document` (for files under `articles/`). No other value. No missing.
- **For concept nodes: `source_file` = the actual .md path**. If you need to reference a concept name mentioned in an article but no such file exists in `vault/wiki/concepts/`, PREFER to reuse an existing concept file whose label matches — do not invent a new concept node without a file unless the term is truly new and important.
- **Every node you create MUST participate in at least one edge or hyperedge.** Forbidden to leave ghost nodes (nodes with no connections). If you create a node and cannot connect it, drop the node.
- **Minimum cross-document semantic density** (applies to this chunk): at least ⌈0.5 × number_of_documents_in_chunk⌉ `semantically_similar_to` edges between different source files, confidence 0.6-0.95. This is how the graph surfaces "these two docs solve the same problem" — if you find zero, you have not looked hard enough; revisit patterns, architectures, customer types, methodologies.
- **Classifying attributes (e.g. region/customer/customer_type in business docs; author/date/source in research docs; platform/language in code docs) SHOULD NOT be independent nodes.** Attach them as node attributes on the document/concept node they describe. Example pattern:
  ```json
  {"id": "doc_xxx", "label": "...", "file_type": "document",
   "<attr1>": "...", "<attr2>": "...", ...}
  ```
  If you need to group by an attribute (e.g. "all docs from region X"), use `hyperedges.grouping_criteria` rather than creating an attribute-as-node.
- Semantic similarity: if two nodes in different source files solve the same problem / describe the same methodology / represent the same idea **without any explicit structural link** (no includes_module/references/applied_to between them), add a `semantically_similar_to` edge, INFERRED, confidence 0.6-0.95. The similarity must be genuinely non-obvious and cross-document — skip trivially similar pairs. Calibrate confidence by strength of overlap:
  - near-synonyms or same architecture pattern with different labels → 0.85-0.95
  - shared methodology with different emphasis → 0.7-0.85
  - weaker but real overlap (same domain, same problem class) → 0.6-0.7
  Domain examples (adapt to your corpus):
    business — two proposals using the same platform architecture for different customers
    research — two papers proposing the same algorithm under different names
    code — two modules implementing the same pattern without importing each other

Collect ALL nodes/edges/hyperedges into ONE JSON structure:
```json
{"nodes": [...], "edges": [...], "hyperedges": [...]}
```

### Step 3 — Build + cluster + analyze + export (ATOMIC)

⚠️ **This step is one atomic CLI call. DO NOT rewrite it as Python; DO NOT hand-craft graph.json / graph.html / index.html / nav/ files. If you cannot execute Bash, STOP and tell the user "execution environment missing".**

First save the Step 2 extraction JSON to a file, then invoke the CLI:

```bash
# Save Step 2 extraction to a file
cat > /tmp/lcwiki-extraction.json <<'EXTRACTEOF'
<PASTE THE EXTRACTION JSON FROM STEP 2 HERE>
EXTRACTEOF

# Atomic Step 3 — builds graph, clusters, analyzes, exports html/json/nav/reports
lcwiki graph-run --kb KB_PATH --extraction /tmp/lcwiki-extraction.json
# If user passed --obsidian, append: --obsidian [--obsidian-dir PATH]

# Post-run verification — MUST pass before continuing to query/audit
lcwiki graph-verify --kb KB_PATH
```

If `graph-verify` returns FAILED, report the specific failure to the user. **Do not** attempt to fix it by writing files manually. The correct response is to rerun Step 2 (fix extraction quality) then Step 3.

<details>
<summary>What graph-run does (for LLM understanding, not for reimplementation)</summary>

`lcwiki graph-run` internally:

1. Validates the extraction JSON schema (nodes have `file_type` + `label`, edges have `relation` from the allowed set, hyperedges have `id` + `members`).
2. Consolidates duplicate node ids that share `source_file`.
3. Backfills concept aliases from summary; merges same-canonical concepts.
4. Builds the directed graph via `lcwiki.build.build_graph`.
5. Attaches hyperedges.
6. Clusters via graspologic, computes cohesion, identifies God Nodes / surprising connections / knowledge gaps / bridges.
7. Auto-labels communities (top-degree concepts, de-duplicated).
8. Writes `graph.json` / `graph.html` / `GRAPH_REPORT_SUMMARY.md` / `GRAPH_REPORT_FULL.md` under `<kb>/vault/graph/`.
9. Writes navigation wiki under `<kb>/vault/wiki/nav/` via `lcwiki.wiki.to_wiki` (one `index.md` + `community-*.md` + `god-*.md`).
10. Writes `graph_index.json` and appends a run report to `<kb>/logs/`.

This is deterministic Python — zero LLM creativity needed. The CLI owns it end-to-end. Your job as the LLM is limited to **producing high-quality Step 2 extraction JSON** (accurate labels, correct relations from the allowed vocabulary, hyperedges where groups of 3+ nodes share a theme, honest confidence scores). Step 3 is not your job.

</details>

<details>
<summary>Legacy reference (the old Python heredoc, here for context — DO NOT paste into Bash)</summary>

```python
# The following is what `lcwiki graph-run` now does internally.
# Kept here so future readers can audit the logic. Running this heredoc
# instead of calling the CLI would skip schema-validation safeguards and
# recent bug fixes — don't do it.

import json, time
from pathlib import Path
from lcwiki.build import build_graph
from lcwiki.cluster import cluster, score_all
from lcwiki.analyze import god_nodes, surprising_connections, knowledge_gaps, bridge_nodes, prune_dangling_edges
from lcwiki.export import to_html, to_json, attach_hyperedges
from lcwiki.report import generate_summary, generate_full
from lcwiki.wiki import to_wiki
from lcwiki.index import save_graph_index, load_concepts_index, save_concepts_index
from lcwiki.merge import (
    merge_extraction_by_aliases, backfill_aliases_from_summary,
    consolidate_by_source_file,
)
from lcwiki.validate import validate_extraction_schema, summarize_issues
from lcwiki.runlog import record_run

_run_started = time.time()
_run_warnings: list = []

kb = Path("KB_PATH")
extraction = EXTRACTION_JSON

# Pre-build step 0: schema check the raw extraction to surface quality
# problems from the subagents (missing label, missing file_type, dangling
# edges, etc.). We do not raise — consolidate_by_source_file below will
# fix many, and the run report will record the before/after delta.
raw_issues = validate_extraction_schema(
    extraction, allowed_file_types={"document", "concept"}
)
if raw_issues:
    print(f"⚠️ 抽取原始数据 {len(raw_issues)} 个 schema 问题:")
    print(f"   分类: {summarize_issues(raw_issues)}")
    _run_warnings.extend(raw_issues[:50])

# Pre-build step A: consolidate nodes that share the same source_file.
# Different subagents may emit different id conventions for one file; this
# collapses them, and backfills any missing label/file_type from the path.
# Domain-agnostic — works for any kb layout / naming style.
extraction, src_redirect = consolidate_by_source_file(extraction)
print(f"✅ 按 source_file 合并 {len(src_redirect)} 个重复 id")

# Re-validate after consolidate to confirm fix + surface any residual issue
post_issues = validate_extraction_schema(
    extraction, allowed_file_types={"document", "concept"}
)
if post_issues:
    print(f"⚠️ consolidate 后仍有 {len(post_issues)} 个问题（留给 /lcwiki audit）:")
    print(f"   分类: {summarize_issues(post_issues)}")
    _run_warnings.extend(post_issues[:30])

# Pre-build step B: fix compile-time alias bug (backfill aliases from summary)
concepts_idx = load_concepts_index(kb / "vault" / "meta")
fixed = backfill_aliases_from_summary(concepts_idx)
if fixed:
    save_concepts_index(concepts_idx, kb / "vault" / "meta")
    print(f"✅ 回填 {fixed} 个 concept 的 aliases（修 compile bug）")

# Pre-build step C: merge alias/synonym nodes via concepts_index aliases.
# Deterministic — only collapses nodes whose label or alias exactly points
# to a canonical concept. No semantic judgment.
extraction, alias_redirect = merge_extraction_by_aliases(extraction, concepts_idx)
print(f"✅ 别名合并 {len(alias_redirect)} 个同义节点")

# NOTE: do NOT auto-filter orphan/ghost nodes here. The /lcwiki graph
# command faithfully records LLM extraction output. If you want to audit
# graph quality (detect suspicious orphans, review edges, etc.), run
# /lcwiki audit — that command puts LLM judgment in the loop before any
# destructive change.

G = build_graph(extraction)
attach_hyperedges(G, extraction.get("hyperedges", []))
pruned = prune_dangling_edges(G)

communities = cluster(G)
cohesion = score_all(G, communities)
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
gaps = knowledge_gaps(G, communities)
bridges = bridge_nodes(G, communities)

# Community labels (auto-generated, de-duplicated).
# Strategy: for each community, pick the top-degree concept(s) as label.
# If label collides with an already-used one, progressively extend with more
# top concepts, and finally fall back to "社区<cid>" to guarantee uniqueness.
labels: dict = {}
used_labels: set[str] = set()
for cid, members in communities.items():
    concepts = [n for n in members if G.nodes[n].get("file_type") == "concept"]
    candidates = concepts if concepts else list(members)
    top = sorted(candidates, key=lambda n: G.degree(n), reverse=True)[:4]

    chosen = f"社区{cid}"
    for k in range(1, len(top) + 1):
        lbl = " / ".join(G.nodes[n].get("label", n) for n in top[:k])
        if lbl and lbl not in used_labels:
            chosen = lbl
            break
    # Final de-dup guard: suffix with community id if still collides
    if chosen in used_labels:
        chosen = f"{chosen} (#{cid})"
    labels[cid] = chosen
    used_labels.add(chosen)

summary = generate_summary(G, communities, labels, gods, cohesion, surprises=surprises)
full = generate_full(G, communities, labels, cohesion, gods, surprises, gaps, bridges=bridges)

graph_dir = kb / "vault" / "graph"
graph_dir.mkdir(parents=True, exist_ok=True)
(graph_dir / "GRAPH_REPORT_SUMMARY.md").write_text(summary, encoding="utf-8")
(graph_dir / "GRAPH_REPORT_FULL.md").write_text(full, encoding="utf-8")
to_json(G, communities, str(graph_dir / "graph.json"))
to_html(G, communities, str(graph_dir / "graph.html"), community_labels=labels)

# Navigation wiki — long-form articles per community + per god node + index.
# Complements the thin concept/*.md (词条) with Wikipedia-style cluster pages.
nav_dir = kb / "vault" / "wiki" / "nav"
nav_count = to_wiki(G, communities, nav_dir, community_labels=labels, cohesion=cohesion, god_nodes_data=gods)
print(f"✅ navigation wiki: {nav_count} 篇（{nav_dir}/index.md）")

# Optional Obsidian vault export (only when --obsidian flag was given)
ENABLE_OBSIDIAN = False        # REPLACE with True when user passed --obsidian
OBSIDIAN_DIR = None            # REPLACE with Path(...) if user passed --obsidian-dir
if ENABLE_OBSIDIAN:
    from lcwiki.export import to_obsidian, to_canvas
    ob_dir = OBSIDIAN_DIR or (graph_dir / "obsidian")
    ob_dir = Path(ob_dir)
    n = to_obsidian(G, communities, str(ob_dir), community_labels=labels, cohesion=cohesion)
    to_canvas(G, communities, str(ob_dir / "graph.canvas"), community_labels=labels)
    print(f"✅ Obsidian vault: {n} notes + graph.canvas → {ob_dir}/")

# Save index
n2c = {}
for cid, nodes in communities.items():
    for n in nodes:
        n2c[n] = cid
n2s = {n: G.nodes[n].get("source_file", "") for n in G.nodes()}
save_graph_index(n2c, dict(communities), n2s, 0, graph_dir)

_isolated = [n for n in G.nodes() if G.degree(n) == 0]
_sem_edges = sum(1 for _, _, d in G.edges(data=True) if d.get("relation") == "semantically_similar_to")
print(f"✅ 图谱：{G.number_of_nodes()} 节点 / {G.number_of_edges()} 边 / {len(communities)} 社区")
print(f"   God Nodes: {', '.join(g['label'] for g in gods[:5])}")
print(f"   孤边清理: {pruned} 条")

# Final: write run report (logs/latest_run.md + logs/run.jsonl + logs/reports/)
_report_path = record_run(
    kb, "graph",
    started_at=_run_started,
    params={"kb_path": str(kb)},
    stats={
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "communities": len(communities),
        "hyperedges": len(extraction.get("hyperedges", [])),
        "isolated_nodes": len(_isolated),
        "semantic_edges": _sem_edges,
        "edges_pruned": pruned,
        "source_file_redirects": len(src_redirect),
        "alias_redirects": len(alias_redirect),
        "schema_issues_raw": len(raw_issues),
        "schema_issues_post": len(post_issues),
        "god_nodes_top5": [g["label"] for g in gods[:5]],
    },
    tokens={},  # subagent tokens are reported separately by the orchestrating LLM
    warnings=_run_warnings,
    status="success" if len(post_issues) == 0 else "partial",
)
if _report_path:
    print(f"📄 运行报告：{_report_path}")
```

</details>

### Step 4 — Report

Read `graph-run` stdout and `GRAPH_REPORT_SUMMARY.md`. Report to the user:
- nodes / edges / communities / hyperedges counts
- top 5 God Nodes
- the most interesting question to try next via `/lcwiki query`

If `graph-verify` reported any FAILED issue, surface it verbatim to the user instead. Do not hide or paper over it.

---

## /lcwiki audit [kb_path]

Manual-trigger graph health check. Unlike `/lcwiki graph`, which faithfully
records LLM extraction output, this command puts LLM judgment into the loop
before any destructive change. Use it when you suspect the graph has noise:
orphan nodes, missing edges, wrong confidence scores, etc.

**Principle**: deterministic code FINDS suspicious items; you (LLM) JUDGE;
user CONFIRMS; only then apply changes.

### Step 0 — Verify graph exists

```bash
test -f KB_PATH/vault/graph/graph.json || echo "missing"
```

If missing, tell user to run `/lcwiki graph` first.

### Step 1 — Find suspicious nodes

```bash
python3 << 'FINDEOF'
import json
from pathlib import Path
from lcwiki.merge import find_orphan_concepts

kb = Path("KB_PATH")  # REPLACE
G_data = json.loads((kb / "vault/graph/graph.json").read_text())
extraction = {
    "nodes": G_data["nodes"],
    "edges": G_data["links"],
    "hyperedges": G_data["graph"].get("hyperedges", []),
}
candidates = find_orphan_concepts(extraction, kb / "vault/wiki/concepts")
print(json.dumps(candidates, ensure_ascii=False, indent=2))
FINDEOF
```

### Step 2 — Gather context per candidate

For EACH candidate, gather evidence before judging:

```bash
# Is the label mentioned anywhere in articles? (a hit suggests a missed edge,
# not an actual ghost — consider RESTORE-EDGE instead of REMOVE)
grep -rl "<candidate_label>" KB_PATH/vault/wiki/articles/
```

Also read the graph.json entry to see if any subtle edges were missed.

### Step 3 — Judge each candidate (LLM decision)

Classify each candidate into one of three actions:

- **REMOVE** — label appears nowhere meaningful, it's a pure extraction artifact (e.g. "数字阅览室" invented by the subagent but never referenced)
- **KEEP** — a legitimate standalone concept/document with its own meaning, even if temporarily unconnected (e.g. a concept file exists but hasn't been referenced by any article yet)
- **RESTORE-EDGE** — the label IS meaningfully mentioned in one or more articles; the LLM just missed the edge during extraction. Propose specific edges to add.

### Step 4 — Present plan to user; wait for confirmation

Show a structured plan:
```
🔎 Audit found N suspicious nodes:
  REMOVE (K): [list of labels + 1-line reason each]
  KEEP   (M): [list + reason]
  RESTORE-EDGE (J): [list + proposed edges]

Reply "确认" to apply.
```

**Do NOT proceed without explicit user confirmation.**

### Step 5 — Apply (only after user confirms)

```bash
python3 << 'APPLYEOF'
import json, shutil, time
from pathlib import Path
import networkx as nx
from networkx.readwrite import json_graph
from lcwiki.merge import apply_orphan_removal

kb = Path("KB_PATH")  # REPLACE
graph_path = kb / "vault/graph/graph.json"

# Always backup first
shutil.copy(graph_path, kb / "vault/graph" / f".graph_backup_audit_{int(time.time())}.json")

G_data = json.loads(graph_path.read_text())
extraction = {
    "nodes": G_data["nodes"],
    "edges": G_data["links"],
    "hyperedges": G_data["graph"].get("hyperedges", []),
}

# From user-confirmed REMOVE list:
removal_ids = [...]  # REPLACE with confirmed ids
extraction = apply_orphan_removal(extraction, removal_ids)

# From user-confirmed RESTORE-EDGE list, append edges:
new_edges = [...]  # REPLACE with proposed edges {source, target, relation, confidence_score, confidence}
extraction["edges"].extend(new_edges)

# Re-serialise using the same format graph.json uses.
G = nx.DiGraph()
for n in extraction["nodes"]:
    G.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
for e in extraction["edges"]:
    G.add_edge(e["source"], e["target"], **{k: v for k, v in e.items() if k not in ("source", "target")})
G.graph["hyperedges"] = extraction["hyperedges"]
data = json_graph.node_link_data(G, edges="links")
graph_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ audit 应用完成: 删除 {len(removal_ids)} 节点, 新增 {len(new_edges)} 边")
APPLYEOF
```

### Step 6 — Report + suggest next

Tell user: removed N, restored M edges. If >10 nodes changed, suggest rerunning `/lcwiki graph` to refresh communities & reports.

### Step 7 — (Optional) Duplicate concept file check

Run this only if the user asks to clean up the `concepts/` directory, or
if you suspect synonym drift (many aliases becoming separate files).

```bash
python3 << 'DUPEOF'
import json
from pathlib import Path
from lcwiki.merge import find_duplicate_concept_files
from lcwiki.index import load_concepts_index

kb = Path("KB_PATH")  # REPLACE
ci = load_concepts_index(kb / "vault/meta")
groups = find_duplicate_concept_files(
    kb / "vault/wiki/concepts",
    ci,
    graph_path=kb / "vault/graph/graph.json",
    semantic_threshold=0.85,
)
print(json.dumps(groups, ensure_ascii=False, indent=2))
DUPEOF
```

Two detection channels are combined:
- **aliases** (high precision): stem matches an alias of another canonical
- **graph_semantic** (high recall): `semantically_similar_to` edge ≥ 0.85

For each group, READ both files (canonical + duplicate) and judge:

- **MERGE**: canonical and duplicates truly describe the same concept — merge duplicate's unique content into canonical's body (usually under a new `## 附注/相关方案` section), then remove the duplicate file.
- **KEEP-SEPARATE**: despite high similarity, they describe distinct concepts (e.g. `新高考选课走班` vs `新高考综合管理` may be parallel components of the same larger system, not synonyms). Just add an alias cross-reference to both summary lines.
- **DEMOTE-TO-ALIAS**: the duplicate is just an alias; remove its file, append its name to canonical's `aliases` field in concepts_index.

Present plan to user; wait for confirmation before applying.

To apply MERGE decisions:

```bash
python3 << 'MERGEEOF'
import json, shutil
from pathlib import Path
from lcwiki.index import load_concepts_index, save_concepts_index

kb = Path("KB_PATH")  # REPLACE
decisions = [  # REPLACE with confirmed decisions
    # {"canonical": "数字基座", "duplicate": "digital-learning-platform",
    #  "extra_section": "## 区域数字基座补充\n\n..."},  # LLM-authored merged content
]
concepts_dir = kb / "vault/wiki/concepts"
ci = load_concepts_index(kb / "vault/meta")

for d in decisions:
    can_p = concepts_dir / f"{d['canonical']}.md"
    dup_p = concepts_dir / f"{d['duplicate']}.md"
    if not (can_p.exists() and dup_p.exists()):
        continue
    # Merge extra content into canonical
    can_text = can_p.read_text(encoding="utf-8")
    if d.get("extra_section"):
        can_p.write_text(can_text.rstrip() + "\n\n" + d["extra_section"] + "\n", encoding="utf-8")
    # Append duplicate name to canonical's aliases in concepts_index
    if d["canonical"] in ci:
        existing = ci[d["canonical"]].get("aliases", [])
        if d["duplicate"] not in existing:
            ci[d["canonical"]]["aliases"] = existing + [d["duplicate"]]
    # Remove the duplicate entry from index and delete the file (with .bak)
    ci.pop(d["duplicate"], None)
    shutil.move(str(dup_p), str(dup_p) + ".bak")

save_concepts_index(ci, kb / "vault/meta")
print(f"✅ 合并完成: {len(decisions)} 组")
MERGEEOF
```

After merging, rerun `/lcwiki graph` so the graph picks up the consolidated concepts.

---

## /lcwiki update [kb_path] <filename_pattern>

**用于"修改过的文件重新入库"场景**。lcwiki 按 sha256 去重，所以同名文件内容一变就当新文件入库、旧版 article/concept/task 变残留。`update` 命令**按文件名清掉旧版所有残留**（软删到 `.trash/`），用户随后 ingest 新版即可。

### 使用

```
# 清掉"Acme" 开头的旧记录（支持子串匹配）
/lcwiki update ~/.openclaw/lcwiki Acme-Corp-Q3-Proposal

# OpenClaw 下 kb_path 可省略（用默认 KB）
/lcwiki update Acme
```

### Step 1 — 查找匹配记录

```bash
python3 << 'UPDATEEOF'
import json
from pathlib import Path
from lcwiki.update import find_matching_records

kb = Path("KB_PATH")  # REPLACE
pattern = "FILENAME_PATTERN"  # REPLACE — 可以是完整文件名或任意子串

matches = find_matching_records(kb, pattern)
print(f"找到 {len(matches)} 条匹配记录:")
for m in matches:
    print(f"  sha={m['sha256'][:12]}  {m['original_filename']}")
    print(f"    raw_path={m['raw_path']}")
    print(f"    generated_pages={m.get('generated_pages', [])}")
UPDATEEOF
```

### Step 2 — 展示每条记录的删除计划（dry-run）

```bash
python3 << 'PLANEOF'
import json
from pathlib import Path
from lcwiki.update import plan_removal

kb = Path("KB_PATH")
TARGET_SHAS = ["SHA1", "SHA2"]  # REPLACE — 从 Step 1 选要更新的（通常就 1 个）

for sha in TARGET_SHAS:
    plan = plan_removal(kb, sha)
    print(f"\n=== 删除计划：{plan['original_filename']} (sha={sha[:12]}) ===")
    print(f"  移除 article: {len(plan['article_files'])} 个")
    for p in plan['article_files']:
        print(f"    - {p}")
    print(f"  移动 archive_dir: {plan['archive_dir']}")
    print(f"  清 staging task: {len(plan['staging_tasks'])} 个")
    print(f"  从 source_map 移除: {plan['source_map_entry']}")
    print(f"  ⚠️ 影响 concept pages: {len(plan['concept_pages_affected'])} 个")
    print(f"     （这些 concept 页会有悬空的 [[旧方案名]] 链接，新 article 编进来后自动恢复）")
PLANEOF
```

### Step 3 — 展示计划给用户，**等待确认**

向用户清晰列出：
```
即将清理 N 篇方案的旧版本：
  - xxx.md (sha=abcd1234)：移除 1 article + archive 目录 + 2 staging tasks
  - yyy.md (sha=ef567890)：移除 1 article + ...

⚠️ 所有文件会移到 `.trash/<timestamp>/`（可恢复，非硬删）
⚠️ 相关 concept 页的 [[旧方案]] 双链会悬空，但你随后 ingest + compile 新版会自动修复

确认执行？
```

**没有用户明确的"确认"字样，不要执行 Step 4。**

### Step 4 — 应用删除（仅在用户确认后）

```bash
python3 << 'APPLYEOF'
import json
from pathlib import Path
from lcwiki.update import plan_removal, apply_removal

kb = Path("KB_PATH")
CONFIRMED_SHAS = ["SHA1"]  # REPLACE with user-confirmed sha list

for sha in CONFIRMED_SHAS:
    plan = plan_removal(kb, sha)
    report = apply_removal(plan, kb, hard_delete=False)  # 软删，到 .trash/
    print(f"✅ 已清理 {plan['original_filename']}")
    print(f"   articles_removed: {len(report['articles_removed'])}")
    print(f"   archive_moved: {report['archive_moved']}")
    print(f"   tasks_removed: {len(report['tasks_removed'])}")
    print(f"   source_map_removed: {report['source_map_removed']}")
    print(f"   trash_dir: {report['trash_dir']}")
APPLYEOF
```

### Step 5 — 提示用户下一步

告诉用户：
```
✅ 旧版已清理到 .trash/。请：
  1. 把新版文件上传到 <kb>/raw/inbox/
  2. 跑 /lcwiki ingest 入库
  3. 跑 /lcwiki compile 重编译
  4. 跑 /lcwiki graph 更新图谱

（受影响的 concept 页的悬空双链会在新 article 生成后自动恢复）

如需彻底删除（不留 .trash/），手动 rm -rf <kb>/.trash/
```

### 可选：一次性批量更新

如果用户说"inbox 里已经是新版，帮我把同名的旧版都清掉再 ingest"：

```bash
python3 << 'CONFLICTEOF'
from pathlib import Path
from lcwiki.update import find_inbox_conflicts

kb = Path("KB_PATH")
conflicts = find_inbox_conflicts(kb)
print(f"检测到 {len(conflicts)} 个 inbox 新文件与已有记录冲突:")
for c in conflicts:
    print(f"  {c['inbox_file'].name}:")
    for r in c['existing_records']:
        print(f"    旧版: {r['original_filename']} (sha={r['sha256'][:12]})")
CONFLICTEOF
```

按 Step 3/4 流程批量确认 + 清理 + ingest。

---

## /lcwiki query [kb_path] "问题" [--filter k=v ...]

### Optional: `--filter` for attribute-bound search

Restrict the starting nodes by frontmatter attributes (region / customer /
customer_type / domain / topic / doc_type). Multi-filter uses AND; multi-value
(comma-separated) uses OR. Examples:

```
/lcwiki query ~/.openclaw/lcwiki "边疆方案有什么特色" --filter region=新疆
/lcwiki query . "民办集团方案架构" --filter customer_type=民办
/lcwiki query . "区域统建方案" --filter region=陕西,新疆 --filter customer_type=民办
```

When no `--filter` is given, all nodes are eligible (default behaviour).

### Step 1 — Read GRAPH_REPORT_SUMMARY.md

If missing, tell user to run `/lcwiki graph` first.

### Step 2 — Find relevant pages (filter-aware)

```bash
python3 << 'QUERYEOF'
import json; from pathlib import Path; import networkx as nx
from networkx.readwrite import json_graph
from lcwiki.query import (
    score_nodes, bfs, subgraph_to_text, find_relevant_wiki_pages,
    parse_filters, read_article_tldrs,
)

kb = Path("KB_PATH")  # REPLACE
G = json_graph.node_link_graph(json.loads((kb / "vault/graph/graph.json").read_text()), edges="links")
terms = ["TERM1", "TERM2"]  # REPLACE with key terms from question
filters = parse_filters(RAW_ARGS)  # REPLACE with cli args list

scored = score_nodes(G, terms, filters=filters)
if not scored and filters:
    print("⚠️ no nodes matched the filter — falling back to unfiltered search")
    scored = score_nodes(G, terms)
start = [nid for _, nid in scored[:3]]
visited, edges = bfs(G, start, depth=3)

# STEP 2 — 读相关 article + concept + nav（上限 6 篇，用相关度+起点加权选出）
pages = find_relevant_wiki_pages(G, visited, kb / "vault/wiki", max_pages=6, start_nodes=start)
print("=== 相关页面（准确性优先，全读）===")
for p in pages:
    print(str(p))
print("\n=== 子图 ===")
print(subgraph_to_text(G, visited, edges, token_budget=2000))

# OPTIONAL: for very large KB where 6 篇全读成本高，可额外扫 tldr 辅助扩展
# （不是替代，而是让 LLM 知道还有哪些 article 的概要可参考）
# tldrs = read_article_tldrs(G, visited, kb / "vault/wiki", max_tldrs=10)
# for t in tldrs: print(f"[tldr] {t['label']}: {t['tldr'][:100]}")
QUERYEOF
```

**关键原则**：准确性 > token 节省。默认 **全读 top-6 pages** 以确保答案完整。TL;DR 只作为可选扩展（当图谱大到 top-6 也覆盖不全时）。

### Step 3 — Read wiki pages (with fallback to content.md)

Read the article/concept pages listed above. If the article has enough information to answer, use it.

**If article information is insufficient** (e.g., article says "原文未涉及" or lacks detail for the question):

Fallback to original content.md:
```bash
python3 -c "
import json, yaml; from pathlib import Path
kb = Path('KB_PATH')  # REPLACE
article_path = Path('ARTICLE_PATH')  # REPLACE with the article that lacks detail

# Read article frontmatter to get source_sha256
text = article_path.read_text(encoding='utf-8')
# Parse frontmatter
if text.startswith('---'):
    fm_end = text.index('---', 3)
    fm = text[3:fm_end].strip()
    for line in fm.split('\n'):
        if line.startswith('source_sha256:'):
            sha = line.split(':',1)[1].strip().strip('\"')
            break

# Find content.md via archive
for content_md in (kb / 'raw' / 'archive').rglob('content.md'):
    if True:  # check all content.md files
        print(f'CONTENT_MD: {content_md}')
        break
"
```

Then use Read tool to read that content.md for full-text detail.

**Three-layer query chain:**
1. **Article** (fast, structured) → answers most questions
2. **content.md** (full text) → answers detail questions article couldn't
3. **original file + images** (assets/) → answers image/chart questions

### Step 4 — Synthesize answer

Generate structured answer. Each point MUST cite source: `[[概念页]] § 章节`

If you used content.md fallback, cite as: `[[文章名]] § 原文详情`

### Step 5 — Save result

```bash
python3 -c "
from pathlib import Path; from lcwiki.query import save_query_result
save_query_result('QUESTION', 'ANSWER', 'bfs', ['NODE1','NODE2'], True, 0, Path('KB_PATH/vault/queries/memory'))
"
```

---

## /lcwiki status [kb_path]

```bash
python3 << 'STATUSEOF'
import json; from pathlib import Path; from lcwiki.compile import list_tasks
kb = Path("KB_PATH")  # REPLACE
wiki = kb / "vault/wiki"
a = len(list((wiki/"articles").glob("*.md"))) if (wiki/"articles").exists() else 0
c = len(list((wiki/"concepts").glob("*.md"))) if (wiki/"concepts").exists() else 0
p = len(list_tasks(kb/"staging", "pending"))
r = len(list_tasks(kb/"staging", "review"))
d = len(list_tasks(kb/"staging", "done"))
gf = kb / "vault/graph/graph.json"
nodes = edges = 0
if gf.exists():
    import networkx as nx; from networkx.readwrite import json_graph
    G = json_graph.node_link_graph(json.loads(gf.read_text()), edges="links")
    nodes, edges = G.number_of_nodes(), G.number_of_edges()
print(f"articles: {a} | concepts: {c}")
print(f"staging: {p} pending / {r} review / {d} done")
print(f"graph: {nodes} nodes / {edges} edges")
STATUSEOF
```

---

## /lcwiki path, explain, correct, lint, watch, benchmark, add, export, serve

These commands follow the same pattern. See the C-skill-design.md for full specifications.
For commands requiring graph.json, tell user to run `/lcwiki graph` first if it doesn't exist.

---

*Skill version: 0.2.0*
