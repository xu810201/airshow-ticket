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

# 先停定时器再传文件：否则 tar 正在覆盖 monitor.py 时恰好撞上 OnCalendar 触发，
# 那一轮会加载到「替换前」的代码，新功能看起来像没生效，很难排查。
echo ">>> 暂停定时器（避免传输过程撞上触发时刻）"
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "systemctl stop airshow-monitor.timer 2>/dev/null || true; echo '    已暂停'"

# 暂停过就一定得恢复，否则监控直接停摆，而且不会有人发现。
# 用「标志位 + trap」双保险：trap 负责异常路径，正常路径在结尾显式恢复并校验。
TIMER_PAUSED=1
TIMER_RESTORED=0

restore_timer() {
  # 只在「暂停过、且还没恢复」时动手，避免正常结尾已经恢复后 trap 再跑一次
  if [ "$TIMER_PAUSED" = "1" ] && [ "$TIMER_RESTORED" = "0" ]; then
    TIMER_RESTORED=1
    ssh -i "$KEY" -o BatchMode=yes "$HOST" \
      "systemctl start airshow-monitor.timer 2>/dev/null || true" || true
  fi
  return 0
}
trap restore_timer EXIT

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

echo ">>> 恢复定时器"
restore_timer

# 光「执行了 start」不算数，要回读 systemd 的真实状态。
# 这里如果只打印状态、不判定，定时器没起来也照样显示「完成」，等于白写。
TIMER_STATE="$(ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "systemctl is-active airshow-monitor.timer 2>/dev/null; systemctl is-enabled airshow-monitor.timer 2>/dev/null")"
# 注意：不能用 ${VAR%%/*} 拆，systemctl 输出自带换行，拆完会剩一个 \n，
# 拿 "active\n" 去比 "active" 永远不相等，校验会误报失败。
ACTIVE="$(printf '%s\n' "$TIMER_STATE" | sed -n '1p')"
ENABLED="$(printf '%s\n' "$TIMER_STATE" | sed -n '2p')"
echo "    状态：$ACTIVE / $ENABLED"

echo ">>> 下一次自动运行："
ssh -i "$KEY" -o BatchMode=yes "$HOST" \
  "systemctl list-timers airshow-monitor.timer --no-pager | sed -n '2p' | sed 's/^/    /'"

if [ "$ACTIVE" != "active" ] || [ "$ENABLED" != "enabled" ]; then
  echo "" >&2
  echo "!!! 定时器没有恢复到运行状态（当前 $ACTIVE / $ENABLED）" >&2
  echo "!!! 监控现在是停摆的，请手动执行：" >&2
  echo "!!!   ssh -i $KEY $HOST 'systemctl start airshow-monitor.timer'" >&2
  exit 1
fi

echo ">>> 完成，定时器已在运行。"
