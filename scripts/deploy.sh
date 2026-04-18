#!/usr/bin/env bash
# lcwiki 一键部署脚本
#
# 从本地 mac 部署到远程 OpenClaw 服务器：
#   打包 wheel → scp → ssh 跑 server-install.sh → 4 步验证
#
# 用法：
#   ./scripts/deploy.sh --host <SERVER_IP> --password 'xxx'
#   ./scripts/deploy.sh --host server.example.com --user root --ssh-key
#
# 前置：
#   macOS 自带 expect（密码模式需要），brew 装的 python3 + build

set -e

# ---------- 参数解析 ----------
HOST=""
USER="root"
PASSWORD=""
USE_SSH_KEY=false
VERSION=""

while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --user) USER="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        --ssh-key) USE_SSH_KEY=true; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        -h|--help)
            cat <<USAGE
用法:
  $0 --host HOST [--user USER] [--password PW | --ssh-key] [--version X.Y.Z]

参数:
  --host HOST       必填。服务器 IP 或域名
  --user USER       可选。SSH 用户名（默认 root）
  --password PW     可选。SSH 密码（不填则使用 ssh key）
  --ssh-key         可选。使用本地 ssh key，不输密码
  --version X.Y.Z   可选。指定 wheel 版本（默认取 dist/ 里最新）
USAGE
            exit 0 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

[ -n "$HOST" ] || { echo "error: --host 必填。用 -h 查看帮助。" >&2; exit 2; }
if [ "$USE_SSH_KEY" = false ] && [ -z "$PASSWORD" ]; then
    read -rsp "Password for $USER@$HOST: " PASSWORD
    echo
fi

# ---------- 定位项目根 ----------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---------- 打包 ----------
echo "━━━ 1. 打包 wheel ━━━"
if [ -z "$VERSION" ]; then
    rm -rf dist/ build/ *.egg-info 2>/dev/null || true
    python3 -m build --wheel 2>&1 | tail -3
fi
WHL=$(ls -t dist/lcwiki-*-py3-none-any.whl 2>/dev/null | head -1)
[ -n "$WHL" ] || { echo "error: dist/ 里没有 wheel，打包失败" >&2; exit 1; }
[ -f docs/server-install.sh ] || { echo "error: docs/server-install.sh 不存在" >&2; exit 1; }
WHL_BASE=$(basename "$WHL")
echo "  wheel: $WHL_BASE"

# ---------- SSH/SCP 辅助 ----------
_run_ssh() {
    local cmd="$1"
    if [ "$USE_SSH_KEY" = true ]; then
        ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$cmd"
    else
        PW="$PASSWORD" expect <<EOF
set timeout 300
set pw \$env(PW)
spawn ssh -o StrictHostKeyChecking=no $USER@$HOST "$cmd"
expect {
    "password:" { send "\$pw\r"; exp_continue }
    eof
}
EOF
    fi
}
_run_scp() {
    local src="$1"
    local dst="$2"
    if [ "$USE_SSH_KEY" = true ]; then
        scp -o StrictHostKeyChecking=no "$src" "$USER@$HOST:$dst"
    else
        PW="$PASSWORD" expect <<EOF
set timeout 120
set pw \$env(PW)
spawn scp -o StrictHostKeyChecking=no "$src" "$USER@$HOST:$dst"
expect {
    "password:" { send "\$pw\r"; exp_continue }
    eof
}
EOF
    fi
}

# ---------- 上传 ----------
echo
echo "━━━ 2. 上传到 $HOST:/tmp/ ━━━"
_run_scp "$WHL" /tmp/
_run_scp docs/server-install.sh /tmp/server-install.sh

# ---------- 安装 ----------
echo
echo "━━━ 3. 服务器跑 server-install.sh ━━━"
_run_ssh "bash /tmp/server-install.sh /tmp/$WHL_BASE 2>&1 | tail -25"

# ---------- 验证 ----------
echo
echo "━━━ 4. 验证 ━━━"
_run_ssh "echo '--- (1) CLI + skill version ---';
lcwiki version;
cat ~/.openclaw/workspace/skills/lcwiki/.lcwiki_version 2>&1;
echo;
echo '--- (2) 模拟 agent 环境能 import lcwiki ---';
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin bash -c 'which lcwiki; lcwiki version; python3 -c \"import lcwiki; print(\\\"lcwiki import OK\\\", lcwiki.__version__)\"';
echo;
echo '--- (3) skill 装对路径（OpenClaw 真读的位置）---';
ls -la ~/.openclaw/workspace/skills/lcwiki/;
echo;
echo '--- (4) 默认 KB 结构完整 ---';
for sub in raw/inbox raw/archive staging/pending vault/wiki/articles vault/wiki/concepts vault/meta vault/graph logs; do
    [ -d ~/.openclaw/lcwiki/\$sub ] && echo \"  OK: \$sub\" || echo \"  MISSING: \$sub\";
done"

echo
echo "━━━ ✅ 部署完成 ━━━"
echo
echo "下一步："
echo "  到飞书 **新开一个对话**，发送 /lcwiki version"
echo "  应答须包含 'lcwiki $(basename "$WHL" | sed 's/lcwiki-\(.*\)-py3.*/\1/')' 和 'Read: from ~/.openclaw/workspace/skills/lcwiki/SKILL.md'"
echo
