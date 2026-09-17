#!/usr/bin/env bash
# 本地跑一轮监控（等价于 GitHub Actions 上做的事）
#
# 用法：
#   ./run-local.sh                 正常检查一轮
#   ./run-local.sh --test-push     只发一条测试推送到手机
#   ./run-local.sh --dry-run -v    只看结果不推送，带详细日志
#
# 凭据来源：同目录下的 local.env（已在 .gitignore 里，不会被提交）。
# 文件格式就一行：
#   PUSHPLUS_TOKEN=你的token

set -euo pipefail
cd "$(dirname "$0")"

# 载入本地凭据（没有这个文件也能跑，只是发不出推送）
if [ -f local.env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./local.env
  set +a
fi

PY=""
for c in python3 /usr/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "没找到 python3，请先安装 Python 3.8+" >&2
  exit 1
fi

exec "$PY" monitor.py "${@:---once}"
