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


def scenario(prev_pages, cur_pages, src_extra=None, first_run_is_current=False):
    """先用 prev_pages 建基线，再用 cur_pages 跑一轮，返回捕获到的推送。

    first_run_is_current=True 时跳过建基线那一步，直接用 cur_pages 当「首次运行」，
    用来验证「首次运行就该告警」这类例外规则。
    """
    with tempfile.TemporaryDirectory() as d:
        src = {"id": "t", "name": "测试源", "url": "https://example.com/a",
               "item_url_pattern": "/Item/", "notify_on_change": True,
               "enabled": True}
        src.update(src_extra or {})
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
            "sources": [src],
        }
        if not first_run_is_current:
            PAGES.clear()
            PAGES.update(prev_pages)
            monitor.run_once(cfg, dry_run=True)    # 首次运行 -> 自动建基线

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


def case(name, prev, cur, expect_critical, src_extra=None, expect_marker=None):
    CASES.append((name, {URL: prev}, {URL: cur}, expect_critical, src_extra, expect_marker))


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

# ---------------------------------------------------------------- 聚合页（真实踩过的坑）
#
# 珠海本地宝这类聚合页，栏目入口是目录式链接（/xiuxian/zhhzmp/），标题叫
# 「第十六届中国航展门票」。它长期挂在页面上，但标题里带“门票”二字，
# 不设 item_url_pattern 的话会被当成“新增票务公告”，直接触发最高级告警。
# 真实文章是 /数字.shtm。下面两条用例锁住这个行为。

AGG_SRC = {"item_url_pattern": r"\.shtm$", "keyword_scan": False}

AGG_BASE = ('<html><body><p>休闲 第十六届中国航展 正文结束</p>'
            '<a href="/xiuxian/zhhzmp/">第十六届中国航展门票</a>'
            '<a href="/xiuxian/106024.shtm">2026第十六届中国航展门票最新消息（持续更新中）'
            '\r\n 2026-09-11</a>'
            '</body></html>')

# 6. 聚合页新增一个栏目导航入口 —— 不应告警
case("聚合页：新增栏目导航项（目录式链接）不得告警", AGG_BASE,
     AGG_BASE.replace('<a href="/xiuxian/zhhzmp/">第十六届中国航展门票</a>',
                      '<a href="/xiuxian/zhhzmp/">第十六届中国航展门票</a>'
                      '<a href="/xiuxian/dswjzghz/">第十六届中国航展</a>'),
     expect_critical=False, src_extra=AGG_SRC)

# 7. 聚合页新增一篇真实文章（标题含门票）—— 必须告警
case("聚合页：新增真实文章（.shtm，标题含门票）要告警", AGG_BASE,
     AGG_BASE + '<a href="/xiuxian/106700.shtm">第十六届中国航展门票开售时间公布</a>',
     expect_critical=True, src_extra=AGG_SRC)

# 8. 已收录文章的发布日期变了 —— 标题变了但不是新公告，不应告警
case("聚合页：已收录文章的日期更新不得当成新公告", AGG_BASE,
     AGG_BASE.replace("2026-09-11", "2026-09-12"),
     expect_critical=False, src_extra=AGG_SRC)

# 9. 聚合页新增一篇跟航展无关、但标题带「票价」的文章 —— 不得告警
#    真实踩过的坑：《2026横琴VAC电音节活动攻略（时间+地点+票价）》，
#    只因为标题里有「票价」二字就被当成航展票务公告。
case("聚合页：无关活动文章的「票价」不得命中票务公告", AGG_BASE,
     AGG_BASE + '<a href="/xiuxian/106632.shtm">2026横琴VAC电音节活动攻略（时间+地点+票价）'
                '\r\n 2026-09-17</a>',
     expect_critical=False, src_extra=AGG_SRC)

# 10. 标题只说「购票入口」、没有开售语义 —— 要推，但文案不能喊「开售信号」
case("聚合页：票务线索要推，但不该喊成开售信号", AGG_BASE,
     AGG_BASE + '<a href="/xiuxian/105349.shtm">2026中国航展购票入口官网\r\n 2026-09-17</a>',
     expect_critical=False, src_extra=AGG_SRC, expect_marker="⚠️")

# 11. 标题明确说开售 —— 必须是「开售信号」
case("聚合页：标题明确开售要用开售文案", AGG_BASE,
     AGG_BASE + '<a href="/xiuxian/105350.shtm">2026中国航展门票正式开售公告'
                '\r\n 2026-09-17</a>',
     expect_critical=True, src_extra=AGG_SRC, expect_marker="🚨")

# ---------------------------------------------------------------- 购票按钮监控
#
# 官网首页的「门票购买」按钮是最硬的信号：未开售时是弹窗占位，
# 开售后换成真实链接。下面几条锁住它的判定，尤其是「注释里的预留写法」。

BTN_SRC = {
    "item_url_pattern": "/Item/",
    "button_watch": [{
        "label": "门票购买",
        "closed_hint": "尚未开放",
        "open_url_pattern": r"piao\.airshow\.com\.cn|ticket",
    }],
}

_HEAD = '<html><body><p>第十六届中国航展门票暂未开售，预计10月官宣票务方案。</p>'

BTN_CLOSED = _HEAD + '<a onclick="alert(\'注册尚未开放，敬请关注!\')">门票购买</a></body></html>'

BTN_OPEN = _HEAD + '<a href="https://piao.airshow.com.cn">门票购买</a></body></html>'

# 官网源码里真实存在的形态：生效的是占位按钮，注释里备着「开售后」的写法
BTN_COMMENTED = (_HEAD
                 + '<a onclick="alert(\'注册尚未开放，敬请关注!\')">门票购买</a>'
                 + '<!-- <a href="https://piao.airshow.com.cn">门票购买</a> -->'
                 + '</body></html>')

# 12. 按钮从弹窗占位变成真实购票链接 —— 必须最高级告警
case("按钮：从占位变成真实购票链接要告警", BTN_CLOSED, BTN_OPEN,
     expect_critical=True, src_extra=BTN_SRC, expect_marker="🚨")

# 13. 注释里预留的「开售后」写法不得被当成已开售（最容易踩的误判）
case("按钮：源码注释里的开售后写法不得误判", BTN_CLOSED, BTN_COMMENTED,
     expect_critical=False, src_extra=BTN_SRC)

# 14. 按钮一直是占位 —— 不告警
case("按钮：一直未开放不得告警", BTN_CLOSED, BTN_CLOSED,
     expect_critical=False, src_extra=BTN_SRC)

# 15. 首次运行（建基线）时按钮就已开放 —— 确定性信号，不能因为“首次”就吞掉
CASES.append(("按钮：首次运行时按钮已开放也要告警",
              {URL: BTN_CLOSED}, {URL: BTN_OPEN}, True, BTN_SRC, "🚨", True))


def main():
    monitor.http_request = fake_http
    monitor.dispatch = fake_dispatch
    passed = failed = 0
    try:
        for item in CASES:
            name, prev, cur, expect_critical, src_extra, expect_marker = item[:6]
            force_baseline = bool(item[6]) if len(item) > 6 else False
            got = scenario(prev, cur, src_extra, force_baseline)
            titles = [g["title"] for g in got]
            is_critical = any("🚨" in t for t in titles)
            if expect_marker is not None:
                ok = any(expect_marker in t for t in titles) and is_critical == expect_critical
            else:
                ok = is_critical == expect_critical
            flag = "PASS" if ok else "FAIL"
            print(f"[{flag}] {name}")
            print(f"       期望开售告警={expect_critical}  实际={is_critical}  "
                  f"推送条数={len(got)}"
                  + (f"  期望文案含 {expect_marker}" if expect_marker else ""))
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
