#!/usr/bin/env bash
# 把 PushPlus token 写进 Linux 服务器的 /opt/airshow-monitor/local.env，并立刻验证。
#
# 用法：
#   ./set-token.sh
#
# 服务器地址/密钥不一样时用环境变量覆盖：
#   AIRSHOW_HOST=deploy@10.0.0.5 AIRSHOW_KEY=~/.ssh/id_ed25519 ./set-token.sh
#
# token 不会出现在命令行参数里（走标准输入），也不会写进本机任何文件。

set -euo pipefail
cd "$(dirname "$0")"

HOST="${AIRSHOW_HOST:-root@192.168.0.10}"
KEY="${AIRSHOW_KEY:-$HOME/.ssh/bomweb_ubuntu}"
DEST="/opt/airshow-monitor"

SSH_OPTS=(-i "$KEY" -o BatchMode=yes -o ConnectTimeout=10)

printf '粘贴 PushPlus token（输入时不显示，回车确认）：'
IFS= read -rs TOKEN
printf '\n'

# 复制 token 时最常见的错误是多带了空格或换行，这里直接清掉，
# 否则服务器上会报「令牌不正确」，查半天查不出来。
TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"

if [ -z "$TOKEN" ]; then
  echo "❌ 没有输入内容，服务器上什么都没改。"
  exit 1
fi
echo "    收到 ${#TOKEN} 个字符，前 4 位：${TOKEN:0:4}***"

echo ">>> 写入 $HOST:$DEST/local.env"
ssh "${SSH_OPTS[@]}" "$HOST" "umask 077 && cat > '$DEST/local.env'" <<EOF
# 由本机 set-token.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 写入
PUSHPLUS_TOKEN=$TOKEN
EOF
ssh "${SSH_OPTS[@]}" "$HOST" "chmod 600 '$DEST/local.env' && echo '    已写入，权限 600'"

echo ">>> 在服务器上验证 token（会往你微信发一条测试消息）"
set +e
OUT="$(ssh "${SSH_OPTS[@]}" "$HOST" \
  "cd '$DEST' && set -a && . ./local.env && set +a && printf '%s' \"\$PUSHPLUS_TOKEN\" | python3 check-push.py" 2>&1)"
RC=$?
set -e
printf '%s\n' "$OUT" | sed 's/^/    /'

echo
if [ "$RC" -ne 0 ]; then
  echo "⚠️ token 没通过验证（见上面【3】结论）。凭据已经写进服务器了，"
  echo "   按提示修好后重跑本脚本即可覆盖。"
  exit "$RC"
fi

echo ">>> token 有效，触发一次完整检查"
ssh "${SSH_OPTS[@]}" "$HOST" \
  "systemctl start airshow-monitor.service || true; journalctl -u airshow-monitor.service -n 12 --no-pager" \
  | sed 's/^/    /'

echo
echo ">>> 完成。以后看状态："
echo "    ssh -i $KEY $HOST 'systemctl list-timers airshow-monitor.timer'"
