#!/usr/bin/env bash
# 一条命令判断「服务器上的监控到底跑没跑起来」。
#
# 用法：
#   ./check-status.sh
#
# 服务器地址/密钥不一样时用环境变量覆盖：
#   AIRSHOW_HOST=deploy@10.0.0.5 AIRSHOW_KEY=~/.ssh/id_ed25519 ./check-status.sh

set -uo pipefail
cd "$(dirname "$0")"

HOST="${AIRSHOW_HOST:-root@192.168.0.10}"
KEY="${AIRSHOW_KEY:-$HOME/.ssh/bomweb_ubuntu}"
DEST="/opt/airshow-monitor"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=10 "$HOST")

pass=0
fail=0
warn=0

ok()   { printf '  \033[32m✅ %s\033[0m\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$1"; fail=$((fail + 1)); }
meh()  { printf '  \033[33m⚠️  %s\033[0m\n' "$1"; warn=$((warn + 1)); }

echo "检查 $HOST:$DEST"
echo

# 先确认能连上，连不上后面的检查全都没意义
if ! "${SSH[@]}" true 2>/dev/null; then
  bad "连不上服务器（检查网络、密钥 $KEY、地址 $HOST）"
  echo
  echo "结论：无法判断，先解决连接问题。"
  exit 1
fi
ok "能连上服务器"

# 远端一次性取回所有事实，避免反复握手
FACTS="$("${SSH[@]}" "
  echo \"ENABLED=\$(systemctl is-enabled airshow-monitor.timer 2>&1)\"
  echo \"ACTIVE=\$(systemctl is-active airshow-monitor.timer 2>&1)\"
  echo \"NEXT=\$(systemctl show airshow-monitor.timer -p NextElapseUSecRealtime --value)\"
  echo \"LASTRUN=\$(systemctl show airshow-monitor.service -p ExecMainStartTimestamp --value)\"
  echo \"EXITCODE=\$(systemctl show airshow-monitor.service -p ExecMainStatus --value)\"
  echo \"RUNCOUNT=\$(journalctl -u airshow-monitor.service --no-pager 2>/dev/null | grep -c 'Starting airshow')\"
  echo \"STATE=\$(stat -c '%s %Y' '$DEST/state/state.json' 2>/dev/null || echo 'MISSING')\"
  echo \"SRCCOUNT=\$(ls '$DEST/state/state.json' >/dev/null 2>&1 && python3 -c \"import json;print(len(json.load(open('$DEST/state/state.json'))['sources']))\" || echo 0)\"
  if grep -q '^PUSHPLUS_TOKEN=.' '$DEST/local.env' 2>/dev/null; then echo \"TOKEN=SET\"; else echo \"TOKEN=MISSING\"; fi
  echo \"LASTLINE=\$(journalctl -u airshow-monitor.service --no-pager -n 200 2>/dev/null | grep '本轮完成' | tail -1 | sed 's/.*本轮完成：//')\"
" 2>/dev/null)"

get() { printf '%s\n' "$FACTS" | sed -n "s/^$1=//p"; }

ENABLED="$(get ENABLED)"; ACTIVE="$(get ACTIVE)"; NEXT="$(get NEXT)"
LASTRUN="$(get LASTRUN)"; EXITCODE="$(get EXITCODE)"; RUNCOUNT="$(get RUNCOUNT)"
STATE="$(get STATE)"; SRCCOUNT="$(get SRCCOUNT)"; TOKEN="$(get TOKEN)"
LASTLINE="$(get LASTLINE)"

# ---- 1. 定时器装好并生效（这是「会不会自动跑」的核心）
[ "$ENABLED" = "enabled" ] && ok "定时器已设为开机自启" \
  || bad "定时器没设开机自启（服务器重启后就停了）→ systemctl enable airshow-monitor.timer"

[ "$ACTIVE" = "active" ] && ok "定时器正在运行" \
  || bad "定时器没在运行 → systemctl start airshow-monitor.timer"

# ---- 2. 有下一次触发时间 = 排班表是活的
case "$NEXT" in
  ""|"n/a"|"0"|"-") bad "定时器没有排下一次触发时间，OnCalendar 可能写错了" ;;
  *) ok "下一次自动运行：$NEXT" ;;
esac

# ---- 3. 真的跑过（RUNCOUNT 含手动触发的）
if [ "${RUNCOUNT:-0}" -ge 1 ]; then
  ok "累计运行过 $RUNCOUNT 次，最近一次：${LASTRUN:-未知}"
else
  bad "一次都没跑过 → 立刻手动验证：systemctl start airshow-monitor.service"
fi

# ---- 4. 上一轮是否正常结束
if [ "$EXITCODE" = "0" ]; then
  ok "上一轮正常结束（退出码 0）"
elif [ "$TOKEN" = "MISSING" ]; then
  meh "上一轮退出码 $EXITCODE —— 因为还没配推送凭据，这是预期行为"
else
  bad "上一轮退出码 $EXITCODE → journalctl -u airshow-monitor.service -n 40 --no-pager"
fi

# ---- 5. 状态文件 = 记录能持久化，重启后不会重复推送
if [ "$STATE" = "MISSING" ]; then
  bad "没有状态文件，还没成功跑完过一轮"
elif [ "${STATE%% *}" -gt 100 ]; then
  ok "状态文件存在（${STATE%% *} 字节），记录了 $SRCCOUNT 个监控源"
else
  meh "状态文件偏小（${STATE%% *} 字节），可能只跑了个开头"
fi

# ---- 6. 凭据 = 能不能真的通知到你
if [ "$TOKEN" = "SET" ]; then
  ok "推送凭据已配置"
else
  bad "推送凭据还没配 → 本地执行 ./set-token.sh（自动写入并验证）"
fi

# ---- 7. 最近一轮的结论
if [ -n "$LASTLINE" ]; then
  case "$LASTLINE" in
    *"成功 ${SRCCOUNT} 个"*) ok "最近一轮：$LASTLINE" ;;
    *) meh "最近一轮：$LASTLINE" ;;
  esac
fi

echo
if [ "$fail" -eq 0 ] && [ "$warn" -eq 0 ]; then
  printf '\033[32m结论：部署成功，且在正常工作。\033[0m\n'
elif [ "$fail" -eq 0 ]; then
  printf '\033[33m结论：机制正常，但有 %d 项待处理（见上面的 ⚠️）。\033[0m\n' "$warn"
else
  printf '\033[31m结论：有 %d 项不通过（见上面的 ❌）。\033[0m\n' "$fail"
  exit 1
fi
