# lcwiki — 企业知识库 Skill

把 Word / PDF / Excel / PPT / 图片 / 音视频编译成**结构化 Wiki + 知识图谱**，支持精准问答与知识库自愈。

核心价值：**让 AI 助手（Claude Code / OpenClaw）在你自己的文档上能准确回答问题，而不是胡编**。

---

## 一、它是什么（大白话）

把一堆文档（比如 37 份方案 Word）丢进 `raw/inbox/`，执行三步：

```
ingest    →  compile    →  graph
解压文件      写概念页+方案摘要   构建知识图谱
```

得到：
- **articles/**：每份文档一篇结构化方案摘要（含 frontmatter 元数据）
- **concepts/**：文档中涉及的概念单独成页（带别名）
- **graph.json + graph.html**：可视化的关系图
- **GRAPH_REPORT_SUMMARY.md**：图谱体检报告

然后就能 `/lcwiki query "我的问题"` 做基于图谱的问答。

---

## 二、核心概念（必须了解）

| 概念 | 大白话 | 目录 |
|------|--------|------|
| **article（方案文档）** | 一整份原始文档的结构化版本 | `vault/wiki/articles/` |
| **concept（概念页）** | 文档中一个知识点的单独词条 | `vault/wiki/concepts/` |
| **frontmatter（文件前言）** | 每个文件开头 `---` 包裹的 YAML 元数据，就像文件身份证 | 每个 .md 头部 |
| **graph（知识图谱）** | 所有 article 和 concept 之间的关系网络 | `vault/graph/` |
| **source_map.json** | sha256 ↔ 原文件 ↔ 生成 article 的追溯表 | `vault/meta/` |
| **audit（体检）** | 手动触发的图谱质量检查（不自动删改） | `/lcwiki audit` 命令 |

---

## 三、安装

### 前置条件

- Python ≥ 3.11
- Claude Code **或** OpenClaw 之一已安装
- 可选：`graspologic`（Leiden 聚类，需 Python 3.13-）

### 步骤 1 — pip 安装 Python 包

```bash
# 克隆仓库
git clone <repo-url> ~/lcwiki
cd ~/lcwiki

# 安装（开发模式，改代码立即生效）
pip install -e .

# 带所有可选依赖
pip install -e ".[all]"

# 验证
lcwiki version
```

### 步骤 2 — 安装 skill 到你的 AI 工具

#### Claude Code
```bash
lcwiki install --platform claude
```
会把 `skill.md` 复制到 `~/.claude/skills/lcwiki/SKILL.md`。

#### OpenClaw
```bash
lcwiki install --platform claw
```
会做两件事：
1. 复制 `skill.md` 到 `~/.openclaw/skills/lcwiki/SKILL.md`
2. 在当前项目根目录的 `AGENTS.md` 里追加 lcwiki 段（让 OpenClaw 的 agents 知道这个项目用了 lcwiki）

### 步骤 3 — 验证

重启 AI 工具，输入 `/lcwiki` —— 应该看到命令提示。

### 卸载

```bash
lcwiki uninstall --platform claude    # 或 claw
```

---

## 四、快速开始（5 分钟跑通）

假设你要建一个知识库，目录叫 `~/my-kb`。

### 1. 准备一份文档

```bash
mkdir -p ~/my-kb/raw/inbox
cp ~/Downloads/你的方案.docx ~/my-kb/raw/inbox/
```

### 2. 三步曲

在 AI 工具里依次输入：

```
/lcwiki ingest ~/my-kb
/lcwiki compile ~/my-kb
/lcwiki graph ~/my-kb
```

### 3. 看结果

```bash
open ~/my-kb/vault/graph/graph.html     # 可视化图谱
cat ~/my-kb/vault/graph/GRAPH_REPORT_SUMMARY.md    # 图谱摘要
ls ~/my-kb/vault/wiki/articles/         # 结构化方案
ls ~/my-kb/vault/wiki/concepts/         # 概念页
```

### 4. 问答

```
/lcwiki query ~/my-kb "我的问题"
```

---

## 五、命令一览表

| 命令 | 作用 | 什么时候用 | 是否需要 LLM |
|------|------|-----------|--------------|
| `/lcwiki ingest [kb]` | 扫描 `raw/inbox/` 转换成 content.md | 每次加入新文件后 | 否（纯 Python 转换）|
| `/lcwiki compile [kb]` | 把 content.md 编译成 article + 抽取 concept | ingest 之后 | **是**（subagent 并行写作）|
| `/lcwiki compile [kb] --deep` | 深度编译（更多 concept，更慢） | 首次建库或大改后 | 是，约 1.5× token |
| `/lcwiki graph [kb]` | 从 articles/concepts 构建知识图谱 | compile 之后，或 audit 后重建 | 是（subagent 抽节点/边）|
| `/lcwiki audit [kb]` | 手动体检图谱（找幽灵节点、重复概念等）| 怀疑图谱质量时 | 是（LLM 做语义判断）|
| `/lcwiki query [kb] "问题"` | 基于图谱的问答 | 日常使用 | 是 |
| `/lcwiki status [kb]` | 查看知识库状态（文件数、图谱指标、最近运行报告） | 任何时候 | 否 |

### 命令参数

- `kb` 是知识库根目录（含 `raw/`、`vault/`、`staging/` 的目录）。省略就用当前目录或对话上下文。
- `compile --deep` 换更长的 prompt，抽更多概念，token 消耗约 1.5 倍，适合**首次建库**或文档质量参差时。

---

## 六、场景化使用指南

### 场景 1：我要从 0 建一个新知识库

```
# 1. 创建目录结构（lcwiki 会自动建缺失的）
mkdir -p ~/my-kb/raw/inbox
cp *.docx *.pdf ~/my-kb/raw/inbox/

# 2. 跑三步曲（第一次用 --deep 保证质量）
/lcwiki ingest ~/my-kb
/lcwiki compile ~/my-kb --deep
/lcwiki graph ~/my-kb

# 3. 体检一遍（建议首次做）
/lcwiki audit ~/my-kb

# 4. 开始使用
/lcwiki query ~/my-kb "..."
```

### 场景 2：我加了几份新文档，要更新知识库

```
cp *.docx ~/my-kb/raw/inbox/       # 放新文件到 inbox
/lcwiki ingest ~/my-kb             # 只处理 inbox 里的新文件（老文件已在 archive）
/lcwiki compile ~/my-kb            # 只 compile 新 article（靠 sha256 去重）
/lcwiki graph ~/my-kb              # 重建 graph（当前实现全量重建）
```

**增量优化提示**：compile 走 staging 队列，已有任务跳过。所以加新文件不会重做旧的。

### 场景 3：我改了某份源文档，要重新编译

```
# 删掉旧产物（或手动把 sha256 从 source_map.json 里移掉）
rm ~/my-kb/vault/wiki/articles/<文档名>.md
# 新版本放回 inbox
cp 新版.docx ~/my-kb/raw/inbox/
/lcwiki ingest ~/my-kb
/lcwiki compile ~/my-kb
/lcwiki graph ~/my-kb
```

### 场景 4：我要问知识库一个问题

```
/lcwiki query ~/my-kb "1+4+2+N 平台体系包括哪些模块？"
```

AI 会：
1. 在图谱里找相关节点（关键词匹配 + 双向 BFS）
2. 读相关 article + concept
3. 如果 article 不够详细 → 回退到原始 `content.md`
4. 综合答案，每句话附引用 `[[概念页]] § 章节`

### 场景 5：图谱看着乱，想体检一下

```
/lcwiki audit ~/my-kb
```

AI 会：
1. 用纯 Python 找可疑节点（幽灵、重复概念）
2. 读文件内容做**语义判断**
3. 给你一份清单：「建议删 N 个 / 保留 M 个 / 合并 K 组」
4. **等你确认**后才应用改动（不自动改）

### 场景 6：好几天没碰了，想看看状态

```
/lcwiki status ~/my-kb
```

会显示：文件数、图谱指标、最近几次运行报告、待处理任务。

---

## 七、知识库目录结构

```
my-kb/
├── raw/                            # 原始文件
│   ├── inbox/                      #   待处理（你往这里丢文件）
│   ├── archive/YYYY-MM-DD/         #   已处理的（sha256 目录）
│   │   └── <sha256>/
│   │       ├── original.docx       #   原文件
│   │       ├── content.md          #   转换后的 markdown
│   │       ├── structure.json      #   结构信息
│   │       └── assets/images/      #   提取的图片
│   └── failed/                     #   处理失败的
├── staging/                        # 任务队列（compile 进度跟踪）
│   ├── pending/                    #   排队中
│   ├── processing/                 #   处理中
│   ├── review/                     #   需人工复核
│   └── failed/                     #   失败的
├── vault/                          # 知识库核心
│   ├── wiki/
│   │   ├── articles/*.md           #   方案文档摘要
│   │   ├── concepts/*.md           #   概念页
│   │   └── decisions/              #   决策记录（可选）
│   ├── meta/
│   │   ├── concepts_index.json     #   概念索引（含别名）
│   │   ├── source_map.json         #   sha256 ↔ 文件追溯
│   │   └── graph_index.json        #   节点 ↔ 社区映射
│   ├── graph/
│   │   ├── graph.json              #   图谱数据
│   │   ├── graph.html              #   可视化（浏览器打开）
│   │   ├── GRAPH_REPORT_SUMMARY.md #   摘要报告
│   │   ├── GRAPH_REPORT_FULL.md    #   详细报告
│   │   └── .graph_backup_*.json    #   自动备份（每次 graph 跑前）
│   └── queries/                    #   问答历史（可选）
└── logs/
    ├── run.jsonl                   # 每次命令运行记录（一行一条 JSON）
    ├── latest_run.md               # 最近一次运行的人类可读报告
    └── reports/                    # 每次运行归档
        └── graph_YYYYMMDD_HHMMSS.md
```

---

## 八、运行报告怎么看

每次跑完 `/lcwiki graph`（以及后续其他命令）都会自动生成报告：

```bash
cat ~/my-kb/logs/latest_run.md
```

看到什么：
- **状态** ✅/⚠️/❌
- **耗时**（秒）
- **统计**：节点数、边数、社区数、孤立节点率、semantic 边数等
- **Token 消耗**：总计 + 分 subagent 分项
- **警告**：schema 检查发现的问题

历史报告在 `logs/reports/` 按命令+时间戳归档。`logs/run.jsonl` 每行一条 JSON 记录，适合脚本统计。

---

## 九、迁移知识库到新机器 / 新系统

**KB 目录是完全可迁移的** —— 所有路径都是相对的，没有绝对路径依赖。

### 迁移步骤

1. **（可选）清理临时文件**减少体积：
   ```bash
   cd my-kb
   rm -f vault/graph/.extract_chunk_*.json
   rm -f vault/graph/.extraction_raw.json
   # 保留最近 1-2 个备份就够了
   ls -t vault/graph/.graph_backup_*.json | tail -n +3 | xargs rm -f
   # 可选：删 .bak 回滚备份（约 1MB）
   find vault/wiki -name "*.bak" -delete
   ```

2. **打包**：
   ```bash
   tar czf my-kb.tar.gz my-kb/
   ```

3. **在新机器解包**：
   ```bash
   tar xzf my-kb.tar.gz
   ```

4. **在新机器安装 lcwiki**（见第三节）

5. **继续使用**：
   ```bash
   /lcwiki status ~/my-kb       # 验证可读
   /lcwiki query ~/my-kb "..."  # 直接用
   ```

**不需要**重新跑 ingest / compile / graph —— 所有产物都在 KB 目录里。

### 迁移性保证

| 项目 | 是否可迁移 | 说明 |
|------|-----------|------|
| 原始文件备份（raw/archive）| ✅ | 按 sha256 组织，跨系统稳定 |
| article / concept `.md` | ✅ | frontmatter 全是相对引用 |
| graph.json | ✅ | 节点的 source_file 是相对路径 |
| source_map.json | ✅ | raw_path 用相对 `raw/archive/...` |
| 运行日志 | ✅ | 纯 JSON / Markdown |
| `.bak` 备份 | ⚠️ | 体积占用，可删 |
| staging 队列 | ✅ | sha256 绑定，跨机器一致 |

### 共享给同事的最小打包

如果只想分享知识（不分享"如何重建"的细节）：
```bash
tar czf my-kb-lite.tar.gz \
  my-kb/vault/wiki \
  my-kb/vault/meta \
  my-kb/vault/graph/graph.json \
  my-kb/vault/graph/graph.html \
  my-kb/vault/graph/GRAPH_REPORT_*.md \
  my-kb/logs/latest_run.md
```

---

## 十、故障排查

### 命令没响应 / 报错 "skill not found"
```bash
lcwiki install --platform claude   # 或 claw
# 重启 Claude Code / OpenClaw
```

### compile 报 "article frontmatter missing fields"
这是**好事** —— schema 校验生效了。检查具体哪个字段缺失：
```bash
cat ~/my-kb/logs/latest_run.md
```
如果是 subagent 输出不规范，重跑 compile 通常能解决；如果持续，提 issue。

### graph 出来的 God Nodes 都是地区/客户
老版本 bug，现已修复。确保你装的是最新版：
```bash
cd ~/lcwiki && git pull && pip install -e . && lcwiki install --platform claude
```

### 跑 graph 花了好几分钟，且跑了 6 个 subagent
这是预期 — Claude Code 并行分派抽取。token 消耗记录在 `logs/latest_run.md` 的 Token 消耗段。OpenClaw 目前顺序处理，时间更长但 token 更少。

### 修了 concept 文件后，graph 不更新
需要重跑 `/lcwiki graph`，它会重新读所有 .md。

### 想把 concepts/ 目录里的同义文件合并
```
/lcwiki audit ~/my-kb
```
走 Step 7（重复概念合并流程）。AI 会找候选、读内容、给建议，**等你确认**再合并。

---

## 十一、常见问题

### Q: 我的文档是英文的，能用吗？
A: 能。lcwiki 不绑定语言 —— subagent prompt 里会告诉它"用源文件的原始语言作 label"。别名解析正则也支持英文 `(aka: X, Y)`。

### Q: 我的文档是代码仓库，能用吗？
A: 能，但如果重点是代码关系图，**建议用 graphify**（lcwiki 的兄弟项目，专为代码设计）。lcwiki 更适合 Word / PDF / 教学文档这类非代码内容。

### Q: graph.html 在公司电脑打不开 / 样式乱
A: graph.html 是纯 HTML + JS + vis.js（CDN）。如果公司网络挡 CDN，加参数 `--offline`（待实现）或手动把 vis.js 下到本地改引用。

### Q: 能离线 / 私有化部署吗？
A: Python 代码 100% 离线。skill 调 LLM 才需要网（Claude Code 或 OpenClaw 自己管账号）。

### Q: 支持多大规模知识库？
A: 当前设计在 30-200 文件规模做过充分测试。更大需要增量 graph 构建（规划中）。

---

## 十二、附录：OpenClaw 下使用

lcwiki 跟 graphify 一样，同时支持 **Claude Code** 和 **OpenClaw** 两个 AI 助手平台。skill 文件本身由对应的 AI 助手加载执行，LLM 调用走该助手自己的后端（Claude API 或 OpenClaw 集成的模型）—— lcwiki 的 Python 代码不直接调 LLM API。

### 12.1 安装

```bash
# 先 pip 装包
pip install -e ~/lcwiki

# 装到 OpenClaw
lcwiki install --platform claw
```

安装会做两件事：
1. 把 `lcwiki/skill-claw.md` 复制到 `~/.openclaw/skills/lcwiki/SKILL.md`
2. 在**当前目录**的 `AGENTS.md` 追加一段 lcwiki 说明（让 OpenClaw 项目里所有 agent 都知道知识库位置）

### 12.2 OpenClaw vs Claude Code 的功能差异

| 维度 | Claude Code | OpenClaw |
|------|-------------|---------|
| compile 阶段 | 并行 subagent（Agent 工具） | 顺序处理（当前多 agent 支持弱） |
| graph 抽取 | 6 subagent 并行抽 | 一次读所有文件，顺序抽 |
| 速度 | 快（~2-5 min / 130 文件）| 慢（~10-15 min） |
| token 消耗 | 略高（并行有少量重复）| 略低（单次抽取无重复） |
| 可靠性 | 偶尔 subagent 失败要重试 | 稳定 |
| AGENTS.md 集成 | 无 | 有（`~/project/AGENTS.md` 自动加段） |

### 12.3 OpenClaw 下的命令

**命令本身一致**（`/lcwiki ingest`、`/lcwiki compile`、`/lcwiki graph`、`/lcwiki audit`、`/lcwiki query`、`/lcwiki status`）。

差异仅在执行方式（内部实现），用户敲命令体验一样。

### 12.4 AGENTS.md 里写了什么

`lcwiki install --platform claw` 会在当前目录的 `AGENTS.md`（OpenClaw 的项目约定文件）追加以下段落：

```markdown
<!-- lcwiki:start -->
## lcwiki

This project uses LLM Wiki for knowledge management. The knowledge graph is in `vault/graph/`.

- Before answering knowledge questions, check `vault/graph/GRAPH_REPORT_SUMMARY.md` and `vault/wiki/index.md`
- After document changes, run `/lcwiki compile` then `/lcwiki graph` to update
- Use `/lcwiki query "question"` for graph-guided Q&A
<!-- lcwiki:end -->
```

作用：OpenClaw 项目里**任何 agent 会话**（不只 lcwiki 技能被触发时）都知道知识库存在。

卸载时 `lcwiki uninstall --platform claw` 会自动移除这段（通过 `<!-- lcwiki:start/end -->` 标记）。

### 12.5 OpenClaw 下的典型工作流

```bash
# 1. 初次使用
cd ~/my-project
lcwiki install --platform claw     # 装 skill + 写 AGENTS.md

# 2. 准备文档
mkdir -p my-project/raw/inbox
cp *.docx my-project/raw/inbox/

# 3. 启动 OpenClaw
claw

# 4. 在 OpenClaw 会话里
/lcwiki ingest my-project
/lcwiki compile my-project
/lcwiki graph my-project
/lcwiki query my-project "我的问题"
```

### 12.6 OpenClaw 专属故障

**问题**：`/lcwiki` 不识别命令
```
# 解决：确认 skill 装对地方
ls ~/.openclaw/skills/lcwiki/SKILL.md
# 如果不在，重装
lcwiki install --platform claw
# 重启 OpenClaw
```

**问题**：compile / graph 跑得很慢
```
# 这是预期，OpenClaw 目前顺序处理。Claude Code 同样知识库可能快 5-10 倍。
# 看 logs/latest_run.md 的 Token 消耗段确认进度。
```

**问题**：AGENTS.md 里有多个工具段落
```
# lcwiki 用 <!-- lcwiki:start --> 和 <!-- lcwiki:end --> 标记自己的段落，
# 不会和 graphify / 其他工具的段冲突。
```

---

## 十三、进阶

### 配置

默认配置在 `lcwiki/_default_config.py`。常见覆盖：
- `compile.chunk_size`：subagent 每批处理文件数（默认 22，文件少可降）
- `compile.max_concepts_per_article`：每篇 article 最多抽几个概念（默认 8）
- `graph.community_algorithm`：`leiden` / `louvain`（leiden 需 graspologic）
- `query.bfs_depth`：BFS 深度（默认 3，大图可调低）

在 kb 根目录放 `config.json` 可覆盖。

### 扩展到其他领域

lcwiki 设计上**不绑定教育领域**。更换到代码库 / 研究论文 / 政策库等，只需要：
1. skill.md 里的 prompt 示例会自动适配（已去硬编码）
2. frontmatter 字段：通用必需字段（title/doc_type/source_sha256/concepts/compiled_by/confidence）不变；领域字段（region/customer 等）改换即可，validate 不会强制

---

## 许可

MIT（详见 LICENSE）

## 致谢

灵感来自 [graphify](https://github.com/...) —— lcwiki 的兄弟项目，专注代码关系图谱。
