#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
触发 GitHub Actions 工作流（外部 cron 服务兜底方案配套工具）

用途：
  1. 验证你的 PAT 有没有触发工作流的权限 —— 配置 cron-job.org 之前先跑这个
  2. 外部 cron 触发失败时，本地手动补一次

用法：
    python3 trigger-workflow.py            # 交互式输入 PAT（不回显）
    python3 trigger-workflow.py --check    # 只验证 PAT，不真正触发
    python3 trigger-workflow.py <PAT>      # 直接传参（会进 shell 历史，不推荐）

PAT 需要什么权限（二选一）：
  · Fine-grained token：Repository access 只选 xu810201/airshow-ticket，
    Permissions → Repository permissions → Actions 设为 Read and write
  · Classic token：勾选 workflow 作用域

创建地址：https://github.com/settings/personal-access-tokens/new
"""

import getpass
import json
import sys
import time
import urllib.error
import urllib.request

OWNER = "xu810201"
REPO = "airshow-ticket"
WORKFLOW = "monitor.yml"
REF = "main"

API = "https://api.github.com"
REPO_URL = f"{API}/repos/{OWNER}/{REPO}"
DISPATCH_URL = f"{API}/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
RUNS_URL = f"{API}/repos/{OWNER}/{REPO}/actions/runs?per_page=1"


def call(url, pat, method="GET", payload=None):
    """返回 (status, body_text, headers_dict)。网络异常时 status 为 None。"""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, body, dict(e.headers or {})
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", {}


def explain(status, body):
    """把 GitHub 的错误码翻译成人话。"""
    if status == 204:
        return "✅ 成功（GitHub 返回 204，工作流已排队）"
    if status == 401:
        return "❌ 401 未认证 —— PAT 填错了，或者已经过期/被删除"
    if status == 403:
        return ("❌ 403 权限不足 —— PAT 没有触发工作流的权限。\n"
                "     Fine-grained token 需要把 Actions 设为 Read and write；\n"
                "     Classic token 需要勾选 workflow 作用域。")
    if status == 404:
        return ("❌ 404 找不到 —— 两种可能：\n"
                "     1) PAT 没有授权访问 xu810201/airshow-ticket 这个仓库\n"
                "     2) 工作流文件名写错了（应为 monitor.yml）")
    if status == 422:
        return "❌ 422 参数错误 —— 通常是 ref 分支名不对（应为 main）"
    return f"❌ HTTP {status}：{body[:300]}"


def main() -> int:
    args = sys.argv[1:]
    check_only = "--check" in args
    args = [a for a in args if a != "--check"]

    if args:
        pat = args[0].strip()
    else:
        pat = getpass.getpass("粘贴 GitHub PAT（输入时不显示，回车确认）：").strip()
    if not pat:
        print("❌ 没有输入 PAT")
        return 1

    print(f"\n目标：{OWNER}/{REPO}  工作流：{WORKFLOW}  分支：{REF}")

    # ---- 1. 验证 PAT 本身
    print("\n【1】验证 PAT")
    status, body, headers = call(REPO_URL, pat)
    if status != 200:
        print("  " + explain(status, body))
        return 1
    try:
        repo = json.loads(body)
        print(f"  ✅ PAT 有效，能访问仓库：{repo['full_name']}（{repo['visibility']}）")
    except Exception:
        print("  ✅ PAT 有效")

    scopes = headers.get("X-Oauth-Scopes") or headers.get("x-oauth-scopes")
    if scopes:
        print(f"  Classic token 作用域：{scopes}")
        if "workflow" not in scopes:
            print("  ⚠️ 作用域里没有 workflow —— 触发工作流会失败，请重新生成 PAT")
    else:
        print("  （Fine-grained token，无法直接读作用域，靠下面实际触发来验证）")

    if check_only:
        print("\n--check 模式，不实际触发。")
        print("要去掉 --check 跑一次，才能确认触发权限。")
        return 0

    # ---- 2. 记录触发前的运行号
    before = None
    s, b, _ = call(RUNS_URL, pat)
    if s == 200:
        try:
            before = json.loads(b)["workflow_runs"][0]["run_number"]
        except Exception:
            pass

    # ---- 3. 触发工作流
    print("\n【2】触发工作流")
    status, body, _ = call(DISPATCH_URL, pat, method="POST", payload={"ref": REF})
    print("  " + explain(status, body))
    if status != 204:
        return 1

    # ---- 4. 确认新运行真的出现了
    print("\n【3】确认运行已创建")
    for i in range(6):
        time.sleep(4)
        s, b, _ = call(RUNS_URL, pat)
        if s != 200:
            continue
        try:
            run = json.loads(b)["workflow_runs"][0]
        except Exception:
            continue
        if before is None or run["run_number"] != before:
            print(f"  ✅ 新运行已出现：#{run['run_number']}（{run['event']}）")
            print(f"     {run['html_url']}")
            print("\n结论：这个 PAT 可以用于 cron-job.org，配置时照抄即可。")
            return 0
        print(f"  …等待中（{i + 1}/6）")
    print("  ⚠️ 没等到新运行。可能只是排队慢，去 Actions 页面确认一下：")
    print(f"     https://github.com/{OWNER}/{REPO}/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
