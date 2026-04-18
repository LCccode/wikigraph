#!/usr/bin/env bash
# =============================================================================
# lcwiki 服务器端安装脚本（OpenClaw 平台）
#
# 前置：已通过 scp 把 lcwiki-<version>-py3-none-any.whl 上传到 /tmp/
#       本脚本不负责 SSH 连接与文件上传，只负责服务器上的安装+初始化+验证
#
# 用法：
#   bash server-install.sh                              # 使用默认 wheel 路径
#   bash server-install.sh /tmp/lcwiki-0.1.0-*.whl      # 指定 wheel
#   PYPI_MIRROR=... bash server-install.sh              # 换 PyPI 镜像源
#
# 默认镜像：清华源（首次直连 pypi.org 易超时）
# =============================================================================

set -e

# ---------- 参数 ----------
WHL="${1:-$(ls /tmp/lcwiki-*-py3-none-any.whl 2>/dev/null | head -1)}"
PYPI_MIRROR="${PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# ---------- 工具函数 ----------
_green() { printf "\033[32m%s\033[0m\n" "$1"; }
_yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
_red() { printf "\033[31m%s\033[0m\n" "$1"; }
_cyan() { printf "\033[36m%s\033[0m\n" "$1"; }

ok()   { _green   "  ✓ $1"; }
warn() { _yellow  "  ⚠ $1"; }
fail() { _red     "  ✗ $1"; exit 1; }
step() { echo; _cyan "━━━ $1 ━━━"; }

# ---------- Step 1: 前置检查 ----------
step "1. 前置环境检查"

command -v python3 >/dev/null || fail "python3 未安装"
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJ=$(echo "$PY_VER" | cut -d. -f1)
PY_MIN=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJ" -ne 3 ] || [ "$PY_MIN" -lt 11 ]; then
    fail "需 Python ≥ 3.11，当前 $PY_VER"
fi
ok "Python $PY_VER"

command -v pip >/dev/null || fail "pip 未安装"
ok "pip: $(pip --version | awk '{print $1, $2}')"

if command -v openclaw >/dev/null; then
    ok "OpenClaw: $(command -v openclaw)"
else
    warn "OpenClaw 未安装（装 lcwiki 后还需 openclaw 才能用 /lcwiki 命令）"
fi

[ -n "$WHL" ] || fail "找不到 wheel 文件（请先 scp 到 /tmp/）"
[ -f "$WHL" ] || fail "wheel 文件不存在: $WHL"
ok "wheel: $WHL ($(du -h "$WHL" | cut -f1))"

# ---------- Step 2: 安装 Python 包 ----------
step "2. 安装 lcwiki Python 包（镜像: $PYPI_MIRROR）"

pip install "$WHL" --force-reinstall -i "$PYPI_MIRROR" --timeout 120 2>&1 | tail -5 | sed 's/^/    /'

LCWIKI_VER_OUT=$(lcwiki version 2>&1)
case "$LCWIKI_VER_OUT" in
    lcwiki*) ok "安装版本: $LCWIKI_VER_OUT" ;;
    *) fail "lcwiki CLI 不可用: $LCWIKI_VER_OUT" ;;
esac

# ---------- Step 2.5: /usr/local/bin/lcwiki wrapper（修 OpenClaw 环境 import 问题）----------
# 问题背景：openclaw-gateway 启动时的 PATH 不包含 /opt/anaconda3/bin，
# 导致 agent 调用 Bash 工具时 which python3 命中 /usr/bin/python3 (3.9)，
# import lcwiki 报 ModuleNotFoundError —— agent 被迫降级手搓。
# 解决：在 /usr/local/bin/lcwiki 放 wrapper，该路径在 openclaw-gateway PATH 里，
# wrapper 转发到 anaconda 的 lcwiki，import 必过。
step "2.5 安装 /usr/local/bin/lcwiki wrapper（让 OpenClaw agent 的 Bash 能找到 lcwiki）"

ANACONDA_LCWIKI=$(command -v lcwiki)
if [ -z "$ANACONDA_LCWIKI" ]; then
    fail "lcwiki CLI 不在 PATH 中（装包失败？）"
fi
cat > /usr/local/bin/lcwiki <<WRAPPER
#!/bin/sh
# lcwiki wrapper (auto-installed by server-install.sh)
# Forwards to the anaconda-installed lcwiki so that callers with a minimal
# PATH (e.g. openclaw-gateway subshells) can still invoke the CLI.
exec "$ANACONDA_LCWIKI" "\$@"
WRAPPER
chmod +x /usr/local/bin/lcwiki
if /usr/local/bin/lcwiki version 2>&1 | grep -q "^lcwiki "; then
    ok "wrapper 生效: /usr/local/bin/lcwiki → $ANACONDA_LCWIKI"
else
    fail "wrapper 无法正常运行，请手工检查 /usr/local/bin/lcwiki"
fi

# ---------- Step 2.6: /usr/local/bin/python3 wrapper（让 skill.md 里 python3 heredoc 也走 anaconda） ----------
# 问题背景：skill.md 的 audit/update/query/status 等命令里还有 python3 << EOF ... from lcwiki.xxx import ...
# heredoc。 在 openclaw 进程的 PATH 下，python3 会命中 /usr/bin/python3 (3.9)，lcwiki import 会失败。
# 解决：在 /usr/local/bin/python3 放 wrapper，该路径在 PATH 中优先于 /usr/bin，强制所有 heredoc 走 anaconda。
# 风险评估：不替换 /usr/bin/python3 本身，只对 PATH 查找 python3 的调用者（agent/shell）生效；
# 系统脚本一般硬编码 /usr/bin/python3 路径，不受影响。
step "2.6 安装 /usr/local/bin/python3 wrapper（让 skill.md 的 python heredoc 走 anaconda）"

ANACONDA_PY=/opt/anaconda3/bin/python3
if [ -x "$ANACONDA_PY" ]; then
    cat > /usr/local/bin/python3 <<'PYWRAPPER'
#!/bin/sh
# python3 wrapper (auto-installed by server-install.sh)
# Forwards PATH-lookup of python3 to the anaconda interpreter that has lcwiki
# installed. This fixes ImportError in skill.md heredocs that call
# `python3 << 'EOF' ... from lcwiki.xxx import ...`.
# Does NOT affect scripts with hardcoded shebang #!/usr/bin/python3.
exec /opt/anaconda3/bin/python3 "$@"
PYWRAPPER
    chmod +x /usr/local/bin/python3
    RESOLVED_PY=$(/usr/local/bin/python3 -c 'import sys; print(sys.executable)' 2>&1)
    LCW_CHECK=$(/usr/local/bin/python3 -c 'import lcwiki; print(lcwiki.__version__)' 2>&1)
    if echo "$LCW_CHECK" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
        ok "python3 wrapper 生效: /usr/local/bin/python3 → $RESOLVED_PY (lcwiki $LCW_CHECK)"
    else
        warn "python3 wrapper 装了但 import lcwiki 失败: $LCW_CHECK"
    fi
else
    warn "找不到 $ANACONDA_PY，跳过 python3 wrapper（audit/query 等命令在 OpenClaw 下可能 import 失败）"
fi

# ---------- Step 3: 初始化 skill + 默认 KB ----------
step "3. 初始化 OpenClaw skill + 默认 KB"

cd "$HOME"
lcwiki install --platform claw 2>&1 | sed 's/^/    /'

# ---------- Step 3.5: 可选装 LibreOffice（支持 .doc / .ppt 旧格式） ----------
step "3.5 (可选) LibreOffice — 支持 .doc / .ppt 旧格式"

if command -v soffice >/dev/null || command -v libreoffice >/dev/null; then
    ok "LibreOffice 已装: $(command -v soffice || command -v libreoffice)"
else
    warn "未检测到 LibreOffice（.doc / .ppt 会在 ingest 阶段被标为 failed）"
    echo ""
    echo "      尝试自动安装 libreoffice-core（免费开源、无 API key、200MB 一次性）"
    # Package names differ across distros:
    #   Debian/Ubuntu:  libreoffice-core  (minimal headless)
    #   RHEL/CentOS/Rocky/Fedora (dnf/yum):  libreoffice-writer + libreoffice-calc  (no -core metapackage)
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y libreoffice-core 2>&1 | tail -3 || \
            warn "apt 安装失败 — 可手动 \`apt install libreoffice-core\`；不阻塞后续"
    elif command -v dnf >/dev/null 2>&1; then
        # 先试最小集（writer 足够做文档转换），失败就试全家桶
        dnf install -y libreoffice-writer libreoffice-calc 2>&1 | tail -3 || \
          dnf install -y libreoffice 2>&1 | tail -3 || \
          warn "dnf 安装失败，不阻塞"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y libreoffice-writer libreoffice-calc 2>&1 | tail -3 || \
          yum install -y libreoffice 2>&1 | tail -3 || \
          warn "yum 安装失败，不阻塞"
    else
        warn "不识别的包管理器，跳过 — 手动装: https://www.libreoffice.org/download/"
    fi

    # 验证：多种可能的 binary 名称
    if command -v soffice >/dev/null 2>&1; then
        ok "LibreOffice 安装成功: $(command -v soffice)"
    elif command -v libreoffice >/dev/null 2>&1; then
        ok "LibreOffice 安装成功: $(command -v libreoffice)"
    else
        warn "安装后仍未检测到 soffice/libreoffice — .doc/.ppt 会跳过，不阻塞其他流程"
    fi
fi

# ---------- Step 4: 四步验证 ----------
step "4. 验证"

SKILL_VER_FILE="$HOME/.openclaw/skills/lcwiki/.lcwiki_version"
if [ -f "$SKILL_VER_FILE" ]; then
    ok "skill 已装: v$(cat "$SKILL_VER_FILE")"
else
    fail "skill 未装到 $SKILL_VER_FILE"
fi

KB_ROOT="$HOME/.openclaw/lcwiki"
for sub in raw/inbox raw/archive staging vault/wiki vault/meta vault/graph logs; do
    [ -d "$KB_ROOT/$sub" ] || fail "KB 目录缺少 $sub"
done
ok "默认 KB 结构完整: $KB_ROOT"

if grep -q "lcwiki:start" "$HOME/AGENTS.md" 2>/dev/null; then
    ok "AGENTS.md 写入 lcwiki 段"
else
    fail "AGENTS.md 缺 lcwiki 段"
fi

if head -15 "$HOME/.openclaw/skills/lcwiki/SKILL.md" | grep -q "OpenClaw 平台专属"; then
    ok "skill 是 OpenClaw 专属版"
else
    fail "skill 不是 OpenClaw 版（可能装错了文件）"
fi

# ---------- Step 5: 总结 ----------
step "✅ 安装完成"

cat << EOF

    默认 KB:     $KB_ROOT
    放文档到:    $KB_ROOT/raw/inbox/

    启动 OpenClaw 后，在对话里发：
      /lcwiki ingest               # 处理新文档
      /lcwiki compile              # 编译 wiki
      /lcwiki graph                # 构建图谱
      /lcwiki query "你的问题"      # 问答
      /lcwiki audit                # 体检

    目录结构一览:
EOF

ls -la "$KB_ROOT" | sed 's/^/      /'

echo
