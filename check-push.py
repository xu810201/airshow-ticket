#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PushPlus token 本地诊断 —— 不经过 GitHub，几秒钟出结果。

用途：当 GitHub Actions 上的测试推送失败时，用这个脚本立刻判断
      是「token 值有问题」还是「网络/其他问题」。

用法：
    python3 check-push.py            # 交互式输入 token，输入时不回显
    python3 check-push.py <token>    # 直接传参（会留在 shell 历史里，不推荐）
    printf '%s' "$PUSHPLUS_TOKEN" | python3 check-push.py   # 从管道读（服务器上推荐）

注意：本脚本只把你的 token 发往 PushPlus 官方接口做验证，不写任何文件、不上传别处。
"""

import getpass
import json
import sys
import urllib.error
import urllib.request

SEND_URL = "https://www.pushplus.plus/send"


def read_token() -> str:
    """按「命令行参数 → 管道 → 交互输入」的优先级取 token。"""
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return getpass.getpass("粘贴 PushPlus token（输入时不显示，回车确认）：").strip()


def main() -> int:
    token = read_token()

    if not token:
        print("❌ 没有输入 token")
        return 1

    # ---- 1. 本地检查 token 本身
    print("\n【1】token 本地检查")
    print(f"  长度        ：{len(token)} 字符")
    print(f"  前 4 位     ：{token[:4]}***")
    has_space = any(c.isspace() for c in token)
    print(f"  含空白字符  ：{'⚠️ 是 —— 复制时多带了空格/换行' if has_space else '✅ 否'}")
    non_ascii = [c for c in token if ord(c) > 127]
    print(f"  含非 ASCII  ：{'⚠️ 是 —— ' + repr(non_ascii[:5]) if non_ascii else '✅ 否'}")
    print(f"  与 pushplus 官网显示的 token 对比一下长度，不一致就是复制错了")

    # ---- 2. 实际调用接口
    print(f"\n【2】调用 PushPlus 接口：POST {SEND_URL}")
    payload = json.dumps(
        {
            "token": token,
            "title": "航展监控 · token 自检",
            "content": "如果你在微信里看到这条消息，说明 token 有效 ✅",
            "template": "txt",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        SEND_URL,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status = r.status
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"  ❌ HTTP {e.code} {e.reason}")
        try:
            print("  " + e.read()[:300].decode("utf-8", "replace"))
        except Exception:
            pass
        return 1
    except Exception as e:
        print(f"  ❌ 网络错误：{type(e).__name__}: {e}")
        print("  （本机到 pushplus.plus 不通，或需要代理）")
        return 1

    print(f"  HTTP {status}")
    print(f"  原始响应：{body[:400]}")

    # ---- 3. 结论
    print("\n【3】结论")
    try:
        j = json.loads(body)
    except Exception:
        print("  ❌ 响应不是合法 JSON，无法判断")
        return 1

    code = j.get("code")
    if code == 200:
        print("  ✅ token 被 PushPlus 接受，请求已受理")
        print("     注意：PushPlus 现在是异步处理，code=200 只代表请求合法。")
        print("     请查看微信是否收到消息；没收到多半是还没关注『pushplus 推送加』公众号。")
        return 0

    print(f"  ❌ token 被 PushPlus 拒绝：code={code} msg={j.get('msg')}")
    print()
    print("     常见原因有两个（按可能性排序）：")
    print("     1) 账号未实名认证 —— PushPlus 要求实名后才能发消息，")
    print("        但报错文案会误导成『令牌不正确』。")
    print("        到 https://www.pushplus.plus/ 登录后，在个人中心完成实名认证。")
    print("     2) token 复制错了 —— 重新复制『一对一推送』那串 token，")
    print("        注意别把『群组编码』或页面 URL 当成 token。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
