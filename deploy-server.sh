#!/usr/bin/env bash
# 把最新代码同步到 Linux 服务器（192.168.0.10:/opt/airshow-monitor）
#
# 用法：
#   ./deploy-server.sh          同步代码 + 语法自检
#   ./deploy-server.sh --restart  同步后立即触发一次检查
#
# 只同步代码，不会覆盖服务器上的 local.env（凭据）和 state/（运行状态）。

set -euo pipefail
cd "$(dirname "$0")"

HOST="${AIRSHOW_HOST:-root@192.168.0.10}"
KEY="${AIRSHOW_KEY:-$HOME/.ssh/bomweb_ubuntu}"
DEST="/opt/airshow-monitor"

FILES="monitor.py config.json check-push.py selftest.py README.md requirements.txt"

echo ">>> 同步到 $HOST:$DEST"
tar czf - $FILES | ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "mkdir -p '$DEST/state' && tar xzf - -C '$DEST' && echo '    文件已就位'"

echo ">>> 服务器上做语法自检"
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "cd '$DEST' && python3 -c \"import ast; [ast.parse(open(f).read()) for f in ('monitor.py','selftest.py','check-push.py')]\" && echo '    语法 OK' && python3 selftest.py 2>&1 | grep -E '^结果' | sed 's/^/    /'"

if [ "${1:-}" = "--restart" ]; then
  echo ">>> 立即触发一次检查"
  ssh -i "$KEY" -o BatchMode=yes "$HOST" \
    "systemctl start airshow-monitor.service || true; journalctl -u airshow-monitor.service -n 12 --no-pager | sed 's/^/    /'"
fi

echo ">>> 完成。查看定时器状态："
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "systemctl list-timers airshow-monitor.timer --no-pager | head -3 | sed 's/^/    /'"
