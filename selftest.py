#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自测脚本：不联网，用模拟页面验证“开售识别 / 否定语境 / 新增公告”的判定逻辑。

    python3 selftest.py
"""

import os
import sys
import tempfile

import monitor

# ---------------------------------------------------------------- 测试脚手架

PAGES = {}
CAPTURED = []
ORIG_HTTP = monitor.http_request
ORIG_DISPATCH = monitor.dispatch


def fake_http(url, **kw):
    if url not in PAGES:
        raise RuntimeError(f"未预置页面：{url}")
    return 200, PAGES[url], url


def fake_dispatch(cfg, title, body, **kw):
    CAPTURED.append({"title": title, "body": body})
    return [("mock", True, "OK")]


def scenario(prev_pages, cur_pages):
    """先用 prev_pages 建基线，再用 cur_pages 跑一轮，返回捕获到的推送。"""
    with tempfile.TemporaryDirectory() as d:
        cfg = {
            "monitor": {"state_file": os.path.join(d, "state.json"),
                        "timeout_seconds": 5, "retries": 1, "proxy": ""},
            "notify": {"title_prefix": "TEST", "max_push_per_run": 5,
                       "change_cooldown_minutes": 0,
                       # 自测里推送是 mock 的，关掉“必须有可用通道”的检查
                       "require_push_channel": False},
            "keywords": monitor.load_config(
                os.path.join(monitor.BASE_DIR, "config.json"))["keywords"],
            "heartbeat": {"enabled": False},
            "push": {},
            "sources": [{"id": "t", "name": "测试源", "url": "https://example.com/a",
                         "item_url_pattern": "/Item/", "notify_on_change": True,
                         "enabled": True}],
        }
        PAGES.clear()
        PAGES.update(prev_pages)
        monitor.run_once(cfg, dry_run=True)        # 首次运行 -> 自动建基线

        CAPTURED.clear()
        PAGES.clear()
        PAGES.update(cur_pages)
        monitor.run_once(cfg, dry_run=False)       # 正式一轮
        return list(CAPTURED)


BASE = ('<html><body><p>第十六届中国航展门票暂未开售，'
        '预计今年10月将统一对外官宣全部票务方案。</p>'
        '<a href="/Item/14509.aspx">第十六届中国航展莲洲展区现场运营及执行管理服务商中标公告</a>'
        '</body></html>')

URL = "https://example.com/a"

# ---------------------------------------------------------------- 用例

CASES = []


def case(name, prev, cur, expect_critical):
    CASES.append((name, {URL: prev}, {URL: cur}, expect_critical))


# 1. 仍是“暂未开售”，只改了日期 —— 不应误报为开售
case("否定语境：仍未开售（仅日期变动）", BASE,
     BASE.replace("第十六届中国航展门票暂未开售",
                  "第十六届中国航展门票暂未开售（更新于 2026-09-18）"),
     expect_critical=False)

# 2. 官方辟谣 + 双重否定 —— 不应误报
case("否定语境：官方辟谣“开售信息均不实”", BASE,
     '<html><body><p>官方辟谣：网传第十六届中国航展门票开售、票价等信息均不实，'
     '目前尚未启动任何售票工作。</p></body></html>',
     expect_critical=False)

# 3. 真正的开售公告 —— 必须告警
case("开售信号：正式公布开售时间与票价", BASE,
     '<html><body><p>第十六届中国航展普通观众门票将于10月15日10:00正式开售，'
     '公众日单日票价500元，购票通道同步在官方小程序开放。</p></body></html>',
     expect_critical=True)

# 4. 新增了一条带“门票/票务”字样的公告 —— 必须告警
case("新增公告：标题命中票务关键词", BASE,
     BASE + '<a href="/Item/14600.aspx">第十六届中国航展门票销售及票价公告</a>',
     expect_critical=True)

# 5. 页面多了一条无关公告 —— 不应升级为开售告警
case("新增公告：与票务无关", BASE,
     BASE + '<a href="/Item/14601.aspx">航展中心9号馆消防设施改造工程招标公告</a>',
     expect_critical=False)


def main():
    monitor.http_request = fake_http
    monitor.dispatch = fake_dispatch
    passed = failed = 0
    try:
        for name, prev, cur, expect_critical in CASES:
            got = scenario(prev, cur)
            is_critical = any("🚨" in g["title"] for g in got)
            ok = is_critical == expect_critical
            flag = "PASS" if ok else "FAIL"
            print(f"[{flag}] {name}")
            print(f"       期望开售告警={expect_critical}  实际={is_critical}  "
                  f"推送条数={len(got)}")
            if got:
                print(f"       标题：{got[0]['title']}")
            if ok:
                passed += 1
            else:
                failed += 1
                if got:
                    print("       ---- 实际消息 ----")
                    print("       " + got[0]["body"].replace("\n", "\n       "))
        print(f"\n结果：{passed} 通过 / {failed} 失败")
    finally:
        monitor.http_request = ORIG_HTTP
        monitor.dispatch = ORIG_DISPATCH
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
