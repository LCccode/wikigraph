# OpenClaw 安装 lcwiki — 完整步骤

本文档描述如何把 lcwiki 安装到 OpenClaw 环境（本机或远程服务器），包括从源码打包 → 分发 → 安装 → 初始化默认 KB 的完整流程。

适用场景：
- 本机开发 + 本机 OpenClaw 使用
- 本机打包 + 上传到服务器部署
- 从 wheel 分发给其他同事安装

---

## 一、前置条件

| 项 | 本机（开发机）| 服务器（部署机）|
|---|---|---|
| Python ≥ 3.11 | ✅ 必需（用于打包）| ✅ 必需（用于安装）|
| `pip` | ✅ 必需 | ✅ 必需 |
| `build` 工具（`python3 -m build`）| ✅ 必需（打包用） | ❌ 不需要 |
| OpenClaw（`openclaw` 命令可用）| 可选 | ✅ 必需 |
| lcwiki 源码 | ✅ 必需 | ❌ 不需要（只需 wheel）|

如果任一机器 Python 版本低于 3.11，用 `pyenv` 或 conda 装个新版本。

---

## 二、路径变量说明

文档里出现的两个"本机路径"变量：

| 变量 | 含义 | 示例 |
|------|------|------|
| `SRC` | lcwiki **源代码**目录（含 `pyproject.toml`）| `~/lcwiki` |
| `DIST` | 打包产物**输出**目录（临时用） | `/tmp/lcwiki-dist` |

这两个只用于本机打包这一步。**服务器上用不到。**

---

## 三、本机 — 打包

源码 → wheel 分发文件。

```bash
SRC=~/lcwiki              # 改成你的源码路径
DIST=/tmp/lcwiki-dist                   # 输出目录（随意）

cd "$SRC"
python3 -m pip install --upgrade build --quiet
python3 -m build --outdir "$DIST"
```

**产出两个文件**：

```
/tmp/lcwiki-dist/
├── lcwiki-0.1.0-py3-none-any.whl       # 二进制分发（推荐安装用）
└── lcwiki-0.1.0.tar.gz                 # 源码分发（sdist）
```

### 打包完成后验证 wheel 内容

```bash
unzip -l "$DIST"/lcwiki-0.1.0-py3-none-any.whl | grep -E "skill|\.py$"
```

应该看到：
- `lcwiki/skill.md`（Claude Code 版）
- `lcwiki/skill-claw.md`（OpenClaw 版）
- 20 个 `.py` 文件

缺 `skill-claw.md` 说明 `pyproject.toml` 里 `package-data` 配置有问题，应该是 `lcwiki = ["skill*.md"]`。

---

## 四、本机 → 服务器 — 传输

用 `scp` 把 wheel 传过去：

```bash
SERVER=YOUR_USER@YOUR_SERVER_HOST       # 改成你的服务器地址
WHL=$(ls "$DIST"/*.whl)

scp "$WHL" "$SERVER:/tmp/"
```

传完后服务器 `/tmp/lcwiki-0.1.0-py3-none-any.whl` 就有了。

> 服务器如果有跳板机、端口非 22、或要走 `rsync`，按自己环境调整即可。核心是把 wheel 搬到服务器。

---

## 五、服务器 — 安装

SSH 上服务器后执行：

```bash
ssh "$SERVER"

# 5.1 前置检查
python3 --version                       # 必须 ≥ 3.11
which openclaw                          # 确保 OpenClaw 已装；如未装先装

# 5.2 安装 lcwiki Python 包
pip install /tmp/lcwiki-0.1.0-py3-none-any.whl --force-reinstall

# 如果系统 Python 无写权限：
#   pip install /tmp/lcwiki-0.1.0-py3-none-any.whl --user
# 如果用 venv / pipx，先进对应环境再装。

# 5.3 验证 CLI 可用
lcwiki version                          # 应输出：lcwiki 0.1.0
```

---

## 六、服务器 — 初始化 skill 和默认 KB

```bash
cd ~                                    # cd 到 home，AGENTS.md 作为全局默认
lcwiki install --platform claw
```

命令一次性完成 4 件事：

```
✅ 复制 skill-claw.md  ->  ~/.openclaw/skills/lcwiki/SKILL.md
✅ 写入全局 AGENTS.md    ->  ~/AGENTS.md（追加 lcwiki 段，标明默认 KB）
✅ 创建默认 KB 骨架      ->  ~/.openclaw/lcwiki/
✅ 写默认 KB README.md   ->  ~/.openclaw/lcwiki/README.md
```

**默认 KB 目录结构**（由 install 自动创建）：

```
~/.openclaw/lcwiki/
├── README.md                           # 默认 KB 使用说明
├── raw/
│   ├── inbox/                          # 🔴 放文档的地方
│   ├── archive/                        # 处理完的原文件（按 sha256）
│   └── failed/
├── staging/                            # 编译任务队列
│   ├── pending/ processing/ review/ failed/
├── vault/                              # 知识库核心（自动填充）
│   ├── wiki/{articles,concepts,decisions,templates}/
│   ├── meta/
│   ├── graph/
│   └── queries/{memory,cache}/
└── logs/
    └── reports/
```

---

## 七、服务器 — 验证

```bash
# 7.1 skill 版本对齐
cat ~/.openclaw/skills/lcwiki/.lcwiki_version
# 应输出：0.1.0

# 7.2 默认 KB 结构完整
ls ~/.openclaw/lcwiki/
# 应看到：README.md  raw/  staging/  vault/  logs/

# 7.3 AGENTS.md 有 lcwiki 段
grep -A 5 "lcwiki" ~/AGENTS.md
# 应看到"默认 KB 在 ~/.openclaw/lcwiki/"等说明

# 7.4 skill 是最新版本（有 OpenClaw 专属说明）
head -15 ~/.openclaw/skills/lcwiki/SKILL.md | grep "📌 OpenClaw"
# 应找到该行
```

---

## 八、日常使用

### 加文档

```bash
# 方式 1：从本机直接 scp 到服务器 KB
scp 方案.docx "$SERVER:~/.openclaw/lcwiki/raw/inbox/"

# 方式 2：服务器上批量复制
ssh "$SERVER"
cp /some/local/path/*.docx ~/.openclaw/lcwiki/raw/inbox/
```

支持格式：`.docx` `.pdf` `.xlsx` `.pptx` `.md` `.txt` `.png` `.jpg` `.mp3` `.mp4` 等。

### 在 OpenClaw 中使用（所有命令无需传路径）

```bash
ssh "$SERVER"
openclaw                                # 启动 OpenClaw 对话

# 在对话框里敲：
#   /lcwiki ingest                      # 扫 inbox → content.md
#   /lcwiki compile                     # 编译 → article + concept
#   /lcwiki graph                       # 构建知识图谱
#   /lcwiki status                      # 查看 KB 状态
#   /lcwiki query "你的问题"             # 问答
#   /lcwiki audit                       # 体检（找幽灵节点/重复概念）
```

### 加新文档（增量）

```bash
# 1. 把新文件丢进 inbox
scp 新方案.docx "$SERVER:~/.openclaw/lcwiki/raw/inbox/"

# 2. 在 OpenClaw 里跑三步
#    /lcwiki ingest      （已处理过的文件按 sha256 自动跳过）
#    /lcwiki compile
#    /lcwiki graph
```

---

## 九、卸载

```bash
ssh "$SERVER"

lcwiki uninstall --platform claw       # 移除 skill + 清理 AGENTS.md
# 默认 KB ~/.openclaw/lcwiki/ 保留（数据在，不自动删）

# 彻底清空（确认后）：
rm -rf ~/.openclaw/lcwiki/
```

也可以 `pip uninstall lcwiki` 彻底移除 Python 包。

---

## 十、故障排查

| 问题 | 原因 / 解决 |
|------|-----------|
| `lcwiki: command not found` | Python 包没装或装到了不在 PATH 的 Python。跑 `which lcwiki` 看在哪；用 `pip show lcwiki` 确认装了 |
| `pip install` 报 `error: externally-managed-environment` | 系统 Python 受保护。换 venv / conda，或加 `--user` / `--break-system-packages` |
| OpenClaw 里 `/lcwiki` 不识别 | 确认 `~/.openclaw/skills/lcwiki/SKILL.md` 存在；重启 OpenClaw |
| `/lcwiki ingest` 问我路径 | skill 不是最新版。重装：`lcwiki install --platform claw` |
| 文档不知道放哪 | 看 `~/.openclaw/lcwiki/README.md` 或本文档第六节 |
| 默认 KB 想换路径 | 当前需显式传：`/lcwiki ingest /path/to/other-kb`；或提 issue 加配置项 |
| 服务器没 OpenClaw | 先装 OpenClaw（另行查 OpenClaw 文档），lcwiki skill 才有地方运行 |

---

## 十一、一键脚本

### 本机一键打包 + 传

```bash
#!/usr/bin/env bash
# save as: pack-and-ship.sh
set -e

SRC=~/lcwiki                    # 改成你的源码路径
DIST=/tmp/lcwiki-dist
SERVER=YOUR_USER@YOUR_SERVER_HOST             # 改成服务器地址

echo "📦 打包..."
cd "$SRC"
python3 -m pip install --upgrade build --quiet
rm -rf "$DIST"
python3 -m build --outdir "$DIST" >/dev/null

WHL=$(ls "$DIST"/*.whl)
echo "   产出: $WHL"

echo "📤 上传到服务器..."
scp "$WHL" "$SERVER:/tmp/"

echo ""
echo "✅ 本机步骤完成。现在 ssh $SERVER 继续 server-side-install.sh"
```

### 服务器一键安装 + 初始化

```bash
#!/usr/bin/env bash
# save as: server-side-install.sh — 放到服务器跑
set -e

WHL="/tmp/lcwiki-0.1.0-py3-none-any.whl"

test -f "$WHL" || { echo "❌ 请先把 $WHL 传到服务器"; exit 1; }

echo "🔍 前置检查..."
python3 --version
which openclaw || echo "⚠️  OpenClaw 未安装，装完 lcwiki 后要再装 OpenClaw 才能用"

echo ""
echo "📥 安装 lcwiki Python 包..."
pip install "$WHL" --force-reinstall
echo "   版本: $(lcwiki version)"

echo ""
echo "🏗️  初始化 skill + 默认 KB..."
cd ~
lcwiki install --platform claw

echo ""
echo "✅ 服务器端就绪"
echo "   丢文档到: ~/.openclaw/lcwiki/raw/inbox/"
echo "   启动 OpenClaw: openclaw → 对话里发 /lcwiki ingest"
```

---

## 十二、版本更新

源码改动后，重跑第三、四、五、六节即可。注意：

- 默认 KB `~/.openclaw/lcwiki/` **不会被覆盖**，里面的文档和图谱都保留
- 只有 `~/.openclaw/skills/lcwiki/SKILL.md` 会被新版 skill-claw.md 覆盖
- AGENTS.md 的 lcwiki 段有标记（`<!-- lcwiki:start -->` / `<!-- lcwiki:end -->`），重装会替换这一段，不会干扰其他工具的段

---

## 附：相关文档

- `README.md` — lcwiki 总体介绍（项目根）
- `lcwiki/skill.md` — Claude Code 平台 skill 源文件
- `lcwiki/skill-claw.md` — OpenClaw 平台 skill 源文件（本文档安装的目标）
- `~/.openclaw/lcwiki/README.md` — 默认 KB 使用说明（install 时自动生成）
