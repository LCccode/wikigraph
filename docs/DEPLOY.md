# lcwiki 部署指南（新手友好版）

> 看这份文档的人：第一次接触 lcwiki，要把它装到新的 OpenClaw 服务器上。
> 看完之后你能做到：从零把 lcwiki 装好，在飞书里用 `/lcwiki` 命令管理知识库。

---

## 第 0 节 · 搞清楚几件事（2 分钟）

### lcwiki 是什么

一个"AI 知识库工具"。你把公司的文档（Word、PDF、Excel 等）丢给它，它会：
1. **ingest（入库）**：把文档转成纯文本存起来
2. **compile（编译）**：让 AI 读每篇文档，生成结构化的 wiki 文章 + 提炼出的概念
3. **graph（图谱）**：把所有文章和概念连成一张关系图
4. **query（问答）**：用自然语言提问，基于知识库回答

### 装完之后是什么样

你在飞书里发 `/lcwiki ingest`，AI 会自动处理 `raw/inbox/` 文件夹里的新文档。
整个链路跑完之后，你能发 `/lcwiki query "XX 方案的预算是多少"`，AI 从知识库里找答案。

### 涉及 3 个地方，别搞混

| 角色 | 作用 | 典型路径 |
|------|------|---------|
| **你的 Mac**（开发机） | 打包 lcwiki、准备部署文件 | `~/lcwiki/` |
| **远程服务器**（装了 OpenClaw 的 Linux） | 实际跑 lcwiki 的地方，知识库数据也存这里 | `/root/.openclaw/lcwiki/` |
| **飞书**（你和 AI 对话的地方） | 发命令给 OpenClaw agent | 飞书聊天窗口 |

**你要做的就是**：在 Mac 上准备好文件 → 送到服务器 → 在服务器上一键装好 → 在飞书里用。

---

## 第 1 节 · 所有关键文件的绝对路径（建议收藏）

### 🖥️ 你的 Mac 上

| 作用 | 绝对路径 |
|------|---------|
| lcwiki 源码根目录 | `~/lcwiki/` |
| 打包命令要在这里执行 | `~/lcwiki/` |
| 打包产出（wheel 文件）的位置 | `~/lcwiki/dist/` |
| 服务器端安装脚本 | `~/lcwiki/docs/server-install.sh` |
| 一键部署脚本（SSH 可达时用） | `~/lcwiki/scripts/deploy.sh` |
| 完整文档（你正在看的） | `~/lcwiki/docs/DEPLOY.md` |

**"wheel 是什么？"** ——就是 Python 的"压缩安装包"，文件名像 `lcwiki-0.4.1-py3-none-any.whl`。你打包一次生成一个，服务器上 `pip install` 这个文件就能装上。

### 🖧 远程服务器上（假设用户是 root）

装完之后会出现这些文件/目录（其他用户把 `/root` 替换成对应 home 即可）：

| 作用 | 绝对路径 |
|------|---------|
| lcwiki CLI 入口（wrapper） | `/usr/local/bin/lcwiki` |
| python3 入口（wrapper） | `/usr/local/bin/python3` |
| lcwiki Python 包真正装在哪 | `/opt/anaconda3/lib/python3.12/site-packages/lcwiki/` |
| **AI 读的 SKILL.md 在这里**（最重要）| `/root/.openclaw/workspace/skills/lcwiki/SKILL.md` |
| skill 版本号 | `/root/.openclaw/workspace/skills/lcwiki/.lcwiki_version` |
| 默认知识库根目录 | `/root/.openclaw/lcwiki/` |
| 用户丢文档进去的收件箱 | `/root/.openclaw/lcwiki/raw/inbox/` |
| 原始文档归档 | `/root/.openclaw/lcwiki/raw/archive/<日期>/<文件名>/` |
| 编译后的 wiki 文章 | `/root/.openclaw/lcwiki/vault/wiki/articles/` |
| 编译后的概念文件 | `/root/.openclaw/lcwiki/vault/wiki/concepts/` |
| 知识图谱（JSON + HTML） | `/root/.openclaw/lcwiki/vault/graph/` |
| 运行日志 + token 成本 | `/root/.openclaw/lcwiki/logs/` |
| 软删除的历史版本 | `/root/.openclaw/lcwiki/.trash/` |

**"为什么要装两个 wrapper？"** ——OpenClaw agent 跑 bash 命令时用的 PATH 里只有 `/usr/local/bin`，没有 anaconda 路径。直接用系统自带的 python3（3.9 版本）会找不到 lcwiki。wrapper 把命令转发给 anaconda 的 python3（3.12 版本），问题就解决了。你不用记细节，装完就好用。

---

## 第 2 节 · 先搞清楚目标服务器满足条件没（3 分钟）

在部署**之前**，确认目标服务器满足下面 4 个条件。**任何一个不满足先别动，否则后面会卡住**。

登录服务器，一条条跑这些命令：

### ① Python 版本 ≥ 3.11

```bash
python3 --version
```
看到 `Python 3.11.x` 或更高就行。如果是 3.9/3.10，**看"遇到问题怎么办 - Q1"**。

### ② 有 anaconda（强烈推荐）

```bash
ls /opt/anaconda3/bin/python3
```
如果存在（能看到文件），OK。如果不存在，**看"遇到问题怎么办 - Q1"**。

### ③ OpenClaw 已装，skill 目录在 `/root/.openclaw/workspace/skills/`

```bash
ls /root/.openclaw/workspace/skills/
```
看到里面有多个文件夹（如 `user-memory`、`skill-creator` 等）就 OK。

如果 `No such file or directory` → OpenClaw 没装，**先装 OpenClaw 再回来**。

如果目录存在但 skill 放在别的地方（比如 `/home/xxx/.openclaw/`），**看"遇到问题怎么办 - Q2"**。

### ④ 你是 root 用户（或有 sudo）

```bash
whoami
```
看到 `root` 就 OK。非 root 也能装，但 `/usr/local/bin/` 下写文件需要 sudo。

---

## 第 3 节 · 部署方式 A — 能 SSH 就一条命令

**适用场景**：你的 Mac 能通过 SSH 连到服务器（能用 `ssh root@<服务器IP>` 登进去）。

### 步骤

在你的 **Mac 上**打开终端：

```bash
cd ~/lcwiki
./scripts/deploy.sh --host <SERVER_IP> --password '你的服务器密码'
```

把 `<SERVER_IP>` 换成真实服务器 IP，把密码换成真实密码。

### 这条命令自动做了什么

1. **打包**：在 `~/lcwiki/dist/` 下生成新的 wheel 文件
2. **传输**：把 wheel + `server-install.sh` 传到服务器的 `/tmp/`
3. **安装**：在服务器上跑 `server-install.sh`
4. **验证**：自动跑 4 步检查（CLI 能用、agent 环境能 import、skill 装对路径、知识库目录结构完整）

### 跑完你会看到

```
━━━ 1. 打包 wheel ━━━
  wheel: lcwiki-0.4.1-py3-none-any.whl

━━━ 2. 上传到 <SERVER_IP>:/tmp/ ━━━
...（上传进度）

━━━ 3. 服务器跑 server-install.sh ━━━
  ✓ skill 已装: v0.4.1
  ✓ 默认 KB 结构完整: /root/.openclaw/lcwiki
  ✓ AGENTS.md 写入 lcwiki 段
  ✓ skill 是 OpenClaw 专属版

━━━ 4. 验证 ━━━
lcwiki 0.4.1
0.4.1
lcwiki import OK 0.4.1
...

━━━ ✅ 部署完成 ━━━
```

**如果看到任何 ❌ 或 MISSING，去"遇到问题怎么办"那一节。**

### 然后去飞书试一下

飞书里**新开一个对话**（别在旧对话里测，会有缓存），发送：

```
/lcwiki version
```

AI 应答里应该看到：
```
📖 Read: from /root/.openclaw/workspace/skills/lcwiki/SKILL.md
🛠️ Exec: lcwiki version
lcwiki 版本：0.4.1
```

**看到这两行 = 部署成功**。去第 5 节看怎么用。

---

## 第 4 节 · 部署方式 B — 不能 SSH，手动 5 步

**适用场景**：
- 堡垒机环境（必须先登堡垒机才能到服务器）
- 隔离网络（Mac 和服务器网络不通）
- 没有 SSH 密码 / 钥匙，只能人工登录
- U 盘摆渡

### Step 1 · 在你的 Mac 上打包 wheel

在 Mac 终端里跑：

```bash
cd ~/lcwiki
rm -rf dist/ build/ *.egg-info
python3 -m build --wheel
ls -lh dist/
```

**预期看到**：
```
total xxx
-rw-r--r--  1 liucheng  staff   150K  ... lcwiki-0.4.1-py3-none-any.whl
```

**如果报错 "No module named build"**，先装 `build` 工具：
```bash
pip3 install build
```

### Step 2 · 确认要搬到服务器的两个文件

这两个文件**必须一起搬到服务器**：

```
~/lcwiki/dist/lcwiki-0.4.1-py3-none-any.whl
~/lcwiki/docs/server-install.sh
```

**"搬到服务器的哪里？"** → 都放到服务器的 `/tmp/` 目录。

**"我怎么搬？"** → 看你的环境，任选一种：

#### 方式 1 · 堡垒机上传（常见）
1. 用堡垒机登录工具（JumpServer / 齐治 / SecureCRT）的"文件上传"功能
2. 把 Mac 上两个文件先传到跳板机
3. 在跳板机 `scp` 到目标服务器 `/tmp/`

#### 方式 2 · U 盘摆渡
1. Mac 上把两个文件拷到 U 盘
2. U 盘插到能访问服务器的机器，或直接插服务器
3. 在服务器上 `cp /mnt/usb/* /tmp/`

#### 方式 3 · 开 HTTP 服务（Mac 和服务器能互相 ping 通就行）
在你的 Mac 上：
```bash
cd ~/lcwiki
python3 -m http.server 8000
```
记下你的 Mac IP（用 `ipconfig getifaddr en0`）。

登到服务器上：
```bash
MAC_IP=192.168.x.x   # 换成你 Mac 的 IP
cd /tmp
wget http://$MAC_IP:8000/dist/lcwiki-0.4.1-py3-none-any.whl
wget http://$MAC_IP:8000/docs/server-install.sh
```

#### 方式 4 · 企业网盘 / 共享盘 / git 仓库
1. 把两个文件上传到公司网盘 / 共享目录 / git
2. 服务器上下载到 `/tmp/`

### Step 3 · 在服务器上确认文件到位

登录服务器（SSH、堡垒机 console、物理机都行），跑：

```bash
ls -la /tmp/lcwiki-0.4.1-py3-none-any.whl /tmp/server-install.sh
```

**预期看到**：两个文件都在，大小正常（wheel ≈ 150 KB，server-install.sh ≈ 9 KB）。

如果某个文件不在，回 Step 2 重新搬。

### Step 4 · 在服务器上一键安装

```bash
bash /tmp/server-install.sh /tmp/lcwiki-0.4.1-py3-none-any.whl
```

**这条命令做了什么**（不用你管，但好奇的话）：

1. 检查 Python 版本和 pip 可用性
2. `pip install` 把 lcwiki 装到 anaconda 的 Python
3. 在 `/usr/local/bin/` 装两个 wrapper（让 OpenClaw 的 agent 能找到对的 python 和 lcwiki）
4. 把 SKILL.md 复制到 `/root/.openclaw/workspace/skills/lcwiki/`（OpenClaw 实际读的位置）
5. 创建默认知识库目录 `/root/.openclaw/lcwiki/`（raw/ vault/ staging/ logs/）
6. （可选）尝试装 LibreOffice，支持老的 .doc / .ppt 格式

**跑完你会看到**类似这样的输出：
```
━━━ 1. 前置环境检查 ━━━
  ✓ Python 3.12.x
  ✓ pip: pip 24.x

━━━ 2. 安装 lcwiki Python 包 ━━━
  ✓ 安装版本: lcwiki 0.4.1

━━━ 2.5 安装 /usr/local/bin/lcwiki wrapper ━━━
  ✓ wrapper 生效

━━━ 2.6 安装 /usr/local/bin/python3 wrapper ━━━
  ✓ python3 wrapper 生效

━━━ 3. 初始化 OpenClaw skill + 默认 KB ━━━
  skill installed  ->  /root/.openclaw/workspace/skills/lcwiki/SKILL.md
  default kb created -> /root/.openclaw/lcwiki

━━━ 4. 验证 ━━━
  ✓ skill 已装: v0.4.1
  ✓ 默认 KB 结构完整: /root/.openclaw/lcwiki
  ✓ AGENTS.md 写入 lcwiki 段
  ✓ skill 是 OpenClaw 专属版

━━━ ✅ 安装完成 ━━━
```

**如果看到任何 ✗ 或红字报错**，去"遇到问题怎么办"那一节对应的条款。

### Step 5 · 服务器上做 4 步验证（复制粘贴就行）

```bash
# === 验证 1：lcwiki CLI 能跑 ===
echo "--- 版本 ---"
lcwiki version
cat /root/.openclaw/workspace/skills/lcwiki/.lcwiki_version

# === 验证 2：agent 模拟环境能 import lcwiki（最关键）===
echo
echo "--- agent 环境测试 ---"
env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin bash -c '
    which lcwiki
    lcwiki version
    python3 -c "import lcwiki; print(\"lcwiki import OK\", lcwiki.__version__)"
'

# === 验证 3：skill 装对路径 ===
echo
echo "--- skill 文件 ---"
ls -la /root/.openclaw/workspace/skills/lcwiki/

# === 验证 4：默认知识库结构完整 ===
echo
echo "--- 知识库目录 ---"
for sub in raw/inbox raw/archive staging/pending vault/wiki/articles vault/wiki/concepts vault/meta vault/graph logs; do
    [ -d /root/.openclaw/lcwiki/$sub ] && echo "  ✓ $sub" || echo "  ✗ MISSING: $sub"
done
```

**每条都要成功**：
- 验证 1：打印 `lcwiki 0.4.1` 和 `0.4.1` 两行
- 验证 2：打印 `/usr/local/bin/lcwiki` + `lcwiki 0.4.1` + `lcwiki import OK 0.4.1`
- 验证 3：看到 `SKILL.md` 和 `.lcwiki_version` 两个文件
- 验证 4：8 个目录都是 ✓，没有任何 `✗ MISSING`

**任何一步失败，先别去飞书测，看"遇到问题怎么办"解决**。

### Step 6 · 到飞书验证

到飞书**新开一个对话**（很重要！），发送：

```
/lcwiki version
```

AI 应答里应该看到：
```
📖 Read: from /root/.openclaw/workspace/skills/lcwiki/SKILL.md
🛠️ Exec: lcwiki version
lcwiki 版本：0.4.1
```

**看到这两行就完美**。

---

## 第 5 节 · 装完之后怎么用

### 给用户的操作手册（飞书里发）

| 命令 | 作用 |
|------|------|
| `/lcwiki ingest` | 处理 `/root/.openclaw/lcwiki/raw/inbox/` 里的新文件 |
| `/lcwiki compile` | 让 AI 读文档、生成 wiki 文章 |
| `/lcwiki graph` | 基于 wiki 生成知识图谱 + HTML 可视化 |
| `/lcwiki query "你的问题"` | 从知识库里找答案 |
| `/lcwiki status` | 看知识库现状（多少文章/概念/pending task）|
| `/lcwiki audit` | 体检图谱：找出有问题的节点（孤立、重复），AI 提修复建议等你确认 |
| `/lcwiki update <filename>` | 清理某个旧版文件（不常用，大部分情况下 ingest 会自动处理）|

### 典型工作流

1. **用户把文档丢进去**（必须丢到服务器上这个目录）：
   ```
   /root/.openclaw/lcwiki/raw/inbox/
   ```
   支持：.docx / .pdf / .xlsx / .md / .txt 等。`.doc` 和 `.ppt` 老格式需要 LibreOffice（安装脚本会尝试装，装不上的话文件会被标 failed）。

2. **在飞书里依次发**：
   ```
   /lcwiki ingest     ← 先入库
   /lcwiki compile    ← 再编译（AI 读文档，生成 wiki）
   /lcwiki graph      ← 再建图谱
   ```

3. **以后随问随答**：
   ```
   /lcwiki query "某方案的预算是多少"
   /lcwiki query "哪些方案用了大模型教师助手"
   ```
   **不用重新跑 ingest/compile/graph**（除非你加了新文件）。

### 增量更新

**如果你加了新文件**：丢进 inbox → 发 `/lcwiki ingest` → `/lcwiki compile` → `/lcwiki graph`。lcwiki 会自动识别新增的、重复的（跳过）、修改过的（清旧版 + 入新版）。

**如果你改了旧文件**（文件名相同，内容不同）：直接覆盖丢到 inbox → `/lcwiki ingest` 会自动把旧版软删到 `.trash/`，然后 compile 新版。不用你手动清理。

---

## 第 6 节 · 升级 lcwiki（已装过旧版，要换新版）

比如从 0.3.1 升到 0.4.1。和首次部署**完全一样**：重跑整个流程，`server-install.sh` 会自动覆盖旧版。

```bash
# 1. 在 Mac 上
cd ~/lcwiki
./scripts/deploy.sh --host <服务器IP> --password '密码'

# 或手动：重走第 4 节的 Step 1-5
```

**⚠️ 一个必须注意的点**：

升级后**用户必须在飞书新开对话**。如果还在旧对话里发命令，AI 会用它记忆里的旧 skill（缓存的），表现会像没升级一样。

**不需要**重启 OpenClaw 服务——磁盘文件刷新了就够。

---

## 第 7 节 · 遇到问题怎么办

### Q1. 服务器 Python 是 3.9，太老

**症状**：跑 `server-install.sh` 第一步报错：
```
✗ 需 Python ≥ 3.11，当前 3.9
```

**原因**：系统自带的 `/usr/bin/python3` 太老，lcwiki 至少要 3.11。

**修复**：装 anaconda（包含 Python 3.12）

```bash
# 下载 anaconda 安装包
cd /tmp
wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh

# 安装到 /opt/anaconda3
bash Anaconda3-2024.10-1-Linux-x86_64.sh -b -p /opt/anaconda3

# 初始化 conda 到你的 shell
/opt/anaconda3/bin/conda init bash
source ~/.bashrc

# 验证
/opt/anaconda3/bin/python3 --version    # 应该 Python 3.12.x

# 重新跑 server-install.sh
bash /tmp/server-install.sh /tmp/lcwiki-0.4.1-py3-none-any.whl
```

**ARM64 服务器**（aarch64）换对应架构的包：`Anaconda3-2024.10-1-Linux-aarch64.sh`。

### Q2. 服务器 OpenClaw 的 skill 目录不在 `/root/.openclaw/workspace/skills/`

**症状**：`ls /root/.openclaw/workspace/skills/` 空或不存在。

**诊断**：找其他 skill 装在哪：
```bash
find /root -name "SKILL.md" 2>/dev/null | head -10
find /home -name "SKILL.md" 2>/dev/null | head -10
```

常见替代位置：
- `/home/<user>/.openclaw/workspace/skills/`（openclaw 跑在非 root 用户下）
- `/root/.claude/skills/`（装成了 Claude Code 版）

**修复**：
1. 如果是非 root 用户跑 openclaw：在那个用户下跑 `server-install.sh`（不用 sudo），lcwiki 会自动装到该用户的 home。
2. 如果是 Claude Code skill 位置：用 `lcwiki install --platform claude`（不是 `claw`），它会装到 `/root/.claude/skills/lcwiki/`（Mac 本地则是 `/Users/<你的用户名>/.claude/skills/lcwiki/`）。

### Q3. 飞书 AI 说找不到 lcwiki 命令

**症状**：飞书发 `/lcwiki version`，AI 报错 `lcwiki: command not found` 或 `ModuleNotFoundError: No module named 'lcwiki'`。

**这几乎 100% 是两个原因之一**：

**原因 A：wrapper 没装上**

登录服务器检查：
```bash
ls -la /usr/local/bin/lcwiki /usr/local/bin/python3
```
如果不存在，手动装：
```bash
ANACONDA_LCWIKI=$(command -v lcwiki)   # 应输出 /opt/anaconda3/bin/lcwiki
cat > /usr/local/bin/lcwiki <<EOF
#!/bin/sh
exec "$ANACONDA_LCWIKI" "\$@"
EOF
chmod +x /usr/local/bin/lcwiki

cat > /usr/local/bin/python3 <<'EOF'
#!/bin/sh
exec /opt/anaconda3/bin/python3 "$@"
EOF
chmod +x /usr/local/bin/python3
```

**原因 B：OpenClaw gateway 进程 PATH 不含 `/usr/local/bin`**

```bash
GW_PID=$(pgrep -f openclaw-gateway | head -1)
tr '\0' '\n' < /proc/$GW_PID/environ | grep ^PATH=
```

如果输出的 PATH 里没有 `/usr/local/bin`，改 gateway 启动脚本（通常 `/root/.openclaw/gateway-daemon.sh`），在启动前 `export PATH=/usr/local/bin:$PATH`，然后重启 gateway。

### Q4. 飞书 AI 不按 skill 做事（自己写 Python 脚本手搓产物）

**症状**：`/lcwiki compile` 之后 `vault/wiki/articles/` 里出现 `<sha8>_标题.md` 这种乱命名，或 concepts/ 里全是 `<sha>_concepts.md` 的空壳文件。

**原因**：skill 没装对路径，AI 读不到新的 SKILL.md，只能凭记忆瞎猜。

**诊断**：
```bash
find /root/.openclaw -name SKILL.md -path '*lcwiki*'
# 必须看到 /root/.openclaw/workspace/skills/lcwiki/SKILL.md

cat /root/.openclaw/workspace/skills/lcwiki/.lcwiki_version
# 应显示当前版本（0.4.1）

grep -c "Execution Bounds\|compile-write\|ATOMIC" /root/.openclaw/workspace/skills/lcwiki/SKILL.md
# 应 ≥ 5（新版 skill 的关键段落数）
```

**修复**：重跑 `server-install.sh`。**然后必须让用户在飞书新开对话**（清理 AI 会话缓存）。

### Q5. `/lcwiki ingest` 说没有待处理文件，但我明明丢了文件

**诊断**：
```bash
ls -la /root/.openclaw/lcwiki/raw/inbox/
ls -la /root/.openclaw/lcwiki/raw/archive/
```

**原因**：文件被识别为"已处理过"（sha 重复），自动删了。这是**正常行为**（防止重复浪费 token）。

如果你**确实想重新 compile 一遍**（比如测试），把对应 sha 从 source_map 里删掉：
```bash
python3 -c "
import json
from pathlib import Path
p = Path('/root/.openclaw/lcwiki/vault/meta/source_map.json')
d = json.loads(p.read_text())
print('current entries:', list(d.keys()))
# 删除不需要的 sha 后 p.write_text(json.dumps(d))
"
```

### Q6. `.doc` / `.ppt` 旧格式文件全部失败

**症状**：ingest 报 `.doc requires LibreOffice (not installed)`。

**修复**：
- Debian/Ubuntu: `apt install -y libreoffice-core`
- RHEL/CentOS: `dnf install -y libreoffice-writer libreoffice-calc`
- **openEuler ARM64**：官方源里可能没有 libreoffice，需要用户手动把 .doc 在 Office 里另存为 .docx 再放 inbox
- **Mac 上预处理**：如果开发机有 Office，批量把 .doc 另存为 .docx 再上传到服务器 inbox

### Q7. 服务器连不上 PyPI（纯内网环境）

**症状**：`server-install.sh` 报 `pip install` 网络超时。

**修复**：在 Mac 上把 lcwiki + 所有依赖打成一个**离线包**，搬过去：

**在 Mac 上**：
```bash
cd ~/lcwiki
mkdir -p /tmp/lcwiki-offline
pip download --dest /tmp/lcwiki-offline dist/lcwiki-0.4.1-py3-none-any.whl
# 会下载所有依赖（networkx、python-docx、openpyxl、pypdf 等）

# 把整个目录打包
cd /tmp
tar czf lcwiki-offline.tar.gz lcwiki-offline/
# 搬运 lcwiki-offline.tar.gz 到服务器
```

**在服务器上**：
```bash
cd /tmp
tar xzf lcwiki-offline.tar.gz
pip install --no-index --find-links /tmp/lcwiki-offline /tmp/lcwiki-offline/lcwiki-0.4.1-py3-none-any.whl

# 然后手工跑 server-install.sh 剩下的步骤（安装 wrapper + install skill）
# 最简单的做法：改 server-install.sh 里 `pip install "$WHL" -i "$PYPI_MIRROR" ...` 那一行
# 改成：pip install "$WHL" --no-index --find-links /tmp/lcwiki-offline
```

---

## 第 8 节 · 参考 · token 成本估算

根据服务器实测数据推算（按 Qwen3.6 Plus 参考价 input ¥0.004/1K、output ¥0.012/1K，具体价格以你的 LLM 厂商为准）：

| 规模 | 一次性 compile + graph 花费 |
|------|------|
| 5 文件 | ≈ **¥2** |
| dozens of docs | ~$2 (one-time) |
| 100 文件 | ≈ **¥28-35** |
| 500 文件 | ≈ **¥140-180** |

**日常 query**：每次 `/lcwiki query "xxx"` ≈ **¥0.04-0.08**。

结论：前期一次性投入构建知识库（几十块），后续长期用便宜。对比传统 RAG 方案（每次问答都要 embed + 召回 + LLM），lcwiki 长期运营成本低很多。

---

## 附 · 关键目录地图（装完后服务器上什么样）

```
/root/.openclaw/
│
├── workspace/
│   └── skills/
│       └── lcwiki/
│           ├── SKILL.md               ← AI 读这里学 lcwiki 命令
│           └── .lcwiki_version        ← 存当前版本号
│
└── lcwiki/                            ← 知识库根目录
    ├── raw/
    │   ├── inbox/                     ← 【用户丢文件到这里】
    │   ├── archive/                   ← 文件归档（按日期分目录）
    │   └── index.jsonl                ← 入库事件日志
    │
    ├── staging/                       ← 待 compile 的任务队列
    │   ├── pending/
    │   ├── processing/
    │   ├── review/                    ← 引入新 concept 的任务（等人工审核）
    │   ├── done/
    │   └── failed/
    │
    ├── vault/
    │   ├── meta/
    │   │   ├── source_map.json        ← sha256 → 原文件 的映射
    │   │   └── concepts_index.json    ← 所有 concept 的别名家族
    │   │
    │   ├── wiki/
    │   │   ├── articles/              ← AI 编译产出的文章（每个原文档一篇）
    │   │   ├── concepts/              ← 提炼的概念（每个概念一个独立文件）
    │   │   └── nav/                   ← 图谱导航页
    │   │
    │   └── graph/
    │       ├── graph.json             ← 知识图谱数据
    │       ├── graph.html             ← 可视化（浏览器打开）
    │       ├── GRAPH_REPORT_*.md      ← 图谱健康报告
    │       └── .extract_chunk_*.json  ← 抽取中间产物
    │
    ├── logs/
    │   ├── compile.log                ← compile 每次任务的日志
    │   ├── cost.jsonl                 ← 每次任务的 token 估算（看成本）
    │   ├── run.jsonl                  ← graph 运行记录
    │   ├── latest_run.md              ← 最近一次 graph 运行的报告
    │   └── reports/                   ← 历史运行报告
    │
    └── .trash/                        ← 软删除目录（auto-update / audit 清理的历史版本）
        └── pre_xxx_<时间戳>/
```

```
/usr/local/bin/
├── lcwiki         ← 转发到 /opt/anaconda3/bin/lcwiki（系统 PATH 能找到）
└── python3        ← 转发到 /opt/anaconda3/bin/python3
```

```
/opt/anaconda3/
└── lib/python3.12/site-packages/
    └── lcwiki/                        ← Python 包真正装在这里
        ├── __main__.py
        ├── ingest.py, compile.py, graph_cmd.py ...
        └── skill-claw.md              ← 源模板（装 OpenClaw 时会复制到 workspace/skills/）
```
