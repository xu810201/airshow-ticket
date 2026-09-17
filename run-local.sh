#!/usr/bin/env bash
# 本地跑一轮监控（等价于 GitHub Actions 上做的事）
# 用法：./run-local.sh           正常检查
#       ./run-local.sh --test-push   只发测试推送

set -euo pipefail
cd "$(dirname "$0")"

PY=""
for c in python3 /usr/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "没找到 python3，请先安装 Python 3.8+" >&2
  exit 1
fi

echo "使用解释器：$PY"
exec "$PY" monitor.py "${@:---once}"
