#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 珠海航展（第十六届中国航展）普通观众门票开售监控 + 手机推送

监控目标：官网公告 / 官网首页 / 官网新闻 / 门票信息页 / 官方票务站 / 第三方聚合页
推送方式：微信（PushPlus / Server酱）、Bark、钉钉、飞书、企业微信、Telegram、自定义 Webhook

零第三方依赖，只用 Python 标准库，任何装了 Python 3.8+ 的地方都能跑。

常用命令：
    python3 monitor.py --once          # 跑一轮（GitHub Actions / cron 用这个）
    python3 monitor.py --test-push     # 只发一条测试推送，验证通道是否打通
    python3 monitor.py --dry-run       # 跑一轮但只打印、不推送
    python3 monitor.py --baseline      # 只建立基线（首次运行自动进入此模式）
    python3 monitor.py --reset         # 清空状态文件，重新建立基线
    python3 monitor.py -v              # 详细日志
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html as htmllib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 基础常量

CST = timezone(timedelta(hours=8))          # 北京时间
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 官方购票渠道（来自官方口径，用于告警消息中提醒用户走正规渠道）
OFFICIAL_CHANNELS = [
    "“中国国际航空航天博览会”官方网站（www.airshow.com.cn / piao.airshow.com.cn）",
    "“中国航展”微信公众号",
    "“珠海航展”微信小程序",
    "“珠海航展”APP",
]

VERBOSE = False
_LOG_FH = None

# ---------------------------------------------------------------- 日志


def now_cst() -> datetime:
    return datetime.now(CST)


def ts() -> str:
    return now_cst().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str, level: str = "INFO") -> None:
    line = f"[{ts()}] [{level}] {msg}"
    print(line, flush=True)
    if _LOG_FH is not None:
        try:
            _LOG_FH.write(line + "\n")
            _LOG_FH.flush()
        except Exception:
            pass


def vlog(msg: str) -> None:
    if VERBOSE:
        log(msg, "DEBUG")


def mask_secret(v: str) -> str:
    """只报告凭据是否存在和长度，绝不打印明文。"""
    v = (v or "").strip()
    if not v:
        return "未设置"
    if len(v) < 12:
        return f"已设置，但只有 {len(v)} 字符 —— 长度偏短，很可能填错了"
    return f"已设置（{len(v)} 字符，{v[:3]}***）"


def write_step_summary(md: str) -> None:
    """把结果写进 GitHub Actions 的 Job Summary，运行页面上直接可见，不用翻日志。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    except Exception as e:
        vlog(f"写 Job Summary 失败：{e}")


# ---------------------------------------------------------------- 配置


_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _interp(node):
    """把配置里的 ${ENV_VAR} 替换成环境变量值（用于 GitHub Secrets）。"""
    if isinstance(node, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), node)
    if isinstance(node, dict):
        return {k: _interp(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_interp(v) for v in node]
    return node


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise SystemExit(f"找不到配置文件：{path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # 允许用整行 // 写注释
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"配置文件 JSON 格式错误：{e}")
    return _interp(cfg)


def resolve_path(p: str) -> str:
    if not p:
        return ""
    return p if os.path.isabs(p) else os.path.join(BASE_DIR, p)


# ---------------------------------------------------------------- HTTP


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: int = 25,
    retries: int = 3,
    proxy: str = "",
    insecure_ssl: bool = False,
):
    """返回 (status_code, body_text, final_url)。失败抛 RuntimeError。"""
    hdr = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if headers:
        hdr.update(headers)

    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl._create_unverified_context() if insecure_ssl else ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)

    retries = max(1, int(retries))
    last_err = "未知错误"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=hdr, method=method)
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return resp.status, _decode(raw), resp.geturl()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = _decode(e.read()[:300])
            except Exception:
                pass
            last_err = f"HTTP {e.code} {e.reason} {body[:100]}"
            # 4xx（除 429 限流）重试没有意义，直接放弃
            if 400 <= e.code < 500 and e.code != 429:
                break
        except Exception as e:  # 超时、DNS、TLS、连接重置……
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            wait = 2 ** attempt
            vlog(f"第 {attempt}/{retries} 次请求失败（{last_err}），{wait}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"请求失败 {url} -> {last_err}")


def http_post_json(url, payload, *, timeout=15, proxy="", insecure_ssl=False, as_json=True):
    if as_json:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ctype = "application/json; charset=utf-8"
    else:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        ctype = "application/x-www-form-urlencoded; charset=utf-8"
    status, text, _ = http_request(
        url,
        method="POST",
        headers={"Content-Type": ctype},
        data=body,
        timeout=timeout,
        retries=2,
        proxy=proxy,
        insecure_ssl=insecure_ssl,
    )
    return status, text


# ---------------------------------------------------------------- 页面解析


_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\u3000\xa0]+")
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
_SENT_RE = re.compile(r"[。！？!?；;\n\r]+")


def html_to_text(html: str) -> str:
    if not html:
        return ""
    h = _COMMENT_RE.sub(" ", html)
    h = _SCRIPT_RE.sub(" ", h)
    h = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", h, flags=re.I)
    h = _TAG_RE.sub(" ", h)
    h = htmllib.unescape(h)
    h = _SPACE_RE.sub(" ", h)
    h = re.sub(r"\n{2,}", "\n", h)
    return h.strip()


def split_sentences(text: str):
    out = []
    for raw in _SENT_RE.split(text or ""):
        s = _SPACE_RE.sub(" ", raw).strip()
        if len(s) >= 6:
            out.append(s)
    return out


def normalize_text(text: str) -> str:
    """归一化：抹掉日期/时间等易变内容，避免误报“页面变化”。"""
    t = re.sub(r"\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}\s*日?", "<DATE>", text)
    t = re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", "<TIME>", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def extract_items(html: str, base_url: str, url_pattern: str | None = None,
                  min_title_len: int = 8, max_items: int = 150):
    """抽取页面里的链接条目（公告列表用），用于发现“新增公告”。"""
    pat = re.compile(url_pattern) if url_pattern else None
    items, seen = [], set()
    for m in _A_RE.finditer(html or ""):
        attrs, inner = m.group(1), m.group(2)
        hm = _HREF_RE.search(attrs)
        if not hm:
            continue
        href = hm.group(1).strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        if pat and not pat.search(href):
            continue
        title = htmllib.unescape(_TAG_RE.sub("", inner))
        title = _SPACE_RE.sub(" ", title).strip()
        if len(title) < min_title_len:
            continue
        if title in seen:
            continue
        seen.add(title)
        items.append({"title": title, "url": urllib.parse.urljoin(base_url, href)})
        if len(items) >= max_items:
            break
    return items


def scan_keywords(text: str, positive, negative, context_len: int = 240):
    """逐句扫描开售关键词，并识别否定语境（“暂未开售”不算命中）。"""
    hits = []
    for s in split_sentences(text):
        matched = [w for w in positive if w in s]
        if not matched:
            continue
        neg = [w for w in negative if w in s]
        snippet = s if len(s) <= context_len else s[:context_len] + "…"
        hits.append({
            "sentence": snippet,
            "words": matched,
            "negated": bool(neg),
            "neg_words": neg,
        })
    return hits


# ---------------------------------------------------------------- 推送通道


def _need(value, hint):
    v = (value or "").strip()
    if not v:
        return None, f"未配置（{hint}）"
    return v, ""


def send_pushplus(cfg, title, body, **kw):
    token, err = _need(cfg.get("token"), "PushPlus Token")
    if err:
        return None, err
    status, text = http_post_json(
        "https://www.pushplus.plus/send",
        {"token": token, "title": title, "content": body, "template": "markdown"},
        **kw,
    )
    try:
        j = json.loads(text)
        code = j.get("code")
        if int(code if code is not None else -1) == 200:
            return True, "OK"
        msg = j.get("msg") or j.get("data") or ""
        if int(code if code is not None else -1) == 903:
            msg = (f"{msg} —— 通常是账号未实名认证（PushPlus 要求实名后才能发消息，"
                   f"但报错会误导成令牌不正确），其次才是 token 复制错误；"
                   f"请到 pushplus.plus 个人中心检查")
        return False, f"code={code} msg={msg}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_serverchan(cfg, title, body, **kw):
    key, err = _need(cfg.get("sendkey"), "Server酱 SendKey")
    if err:
        return None, err
    # Server酱³ 的 key 以 sctp 开头，走独立域名；Turbo 版走 sctapi
    if key.startswith("sctp"):
        url = f"https://{key}.push.ft07.com/send"
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    status, text = http_post_json(
        url, {"title": title[:32], "desp": body}, as_json=False, **kw
    )
    try:
        j = json.loads(text)
        if int(j.get("code", -1)) == 0:
            return True, "OK"
        return False, f"code={j.get('code')} msg={j.get('message') or j.get('msg')}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_bark(cfg, title, body, **kw):
    key, err = _need(cfg.get("key"), "Bark 设备 Key")
    if err:
        return None, err
    server = (cfg.get("server") or "https://api.day.app").rstrip("/")
    status, text = http_post_json(
        f"{server}/push",
        {
            "device_key": key,
            "title": title,
            "body": body,
            "group": cfg.get("group", "航展门票"),
        },
        **kw,
    )
    try:
        j = json.loads(text)
        return int(j.get("code", 200)) == 200, f"code={j.get('code')} msg={j.get('message')}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_dingtalk(cfg, title, body, **kw):
    url, err = _need(cfg.get("webhook"), "钉钉机器人 Webhook")
    if err:
        return None, err
    status, text = http_post_json(
        url, {"msgtype": "markdown", "markdown": {"title": title, "text": f"## {title}\n\n{body}"}}, **kw
    )
    try:
        j = json.loads(text)
        return int(j.get("errcode", -1)) == 0, f"errcode={j.get('errcode')} {j.get('errmsg')}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_feishu(cfg, title, body, **kw):
    url, err = _need(cfg.get("webhook"), "飞书机器人 Webhook")
    if err:
        return None, err
    status, text = http_post_json(
        url, {"msg_type": "text", "content": {"text": f"{title}\n\n{body}"}}, **kw
    )
    try:
        j = json.loads(text)
        return int(j.get("code", -1)) == 0, f"code={j.get('code')} {j.get('msg')}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_wecom(cfg, title, body, **kw):
    url, err = _need(cfg.get("webhook"), "企业微信机器人 Webhook")
    if err:
        return None, err
    status, text = http_post_json(
        url, {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n\n{body}"}}, **kw
    )
    try:
        j = json.loads(text)
        return int(j.get("errcode", -1)) == 0, f"errcode={j.get('errcode')} {j.get('errmsg')}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_telegram(cfg, title, body, **kw):
    token, err = _need(cfg.get("bot_token"), "Telegram Bot Token")
    if err:
        return None, err
    chat_id, err2 = _need(cfg.get("chat_id"), "Telegram chat_id")
    if err2:
        return None, err2
    status, text = http_post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {
            "chat_id": chat_id,
            "text": f"*{title}*\n\n{body}",
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        },
        **kw,
    )
    try:
        j = json.loads(text)
        return bool(j.get("ok")), f"ok={j.get('ok')} {str(j.get('description'))[:100]}"
    except Exception:
        return status == 200, f"HTTP {status} {text[:140]}"


def send_webhook(cfg, title, body, **kw):
    url, err = _need(cfg.get("url"), "自定义 Webhook 地址")
    if err:
        return None, err
    status, text = http_post_json(url, {"title": title, "body": body}, **kw)
    return 200 <= status < 300, f"HTTP {status} {text[:140]}"


CHANNELS = {
    "pushplus": send_pushplus,
    "serverchan": send_serverchan,
    "bark": send_bark,
    "dingtalk": send_dingtalk,
    "feishu": send_feishu,
    "wecom": send_wecom,
    "telegram": send_telegram,
    "webhook": send_webhook,
}

CHANNEL_LABELS = {
    "pushplus": "PushPlus（微信）",
    "serverchan": "Server酱（微信）",
    "bark": "Bark（iPhone）",
    "dingtalk": "钉钉机器人",
    "feishu": "飞书机器人",
    "wecom": "企业微信机器人",
    "telegram": "Telegram",
    "webhook": "自定义 Webhook",
}

# 各通道的主凭据字段，用于预检时判断“启用了但没填凭据”
CRED_FIELDS = {
    "pushplus": "token",
    "serverchan": "sendkey",
    "bark": "key",
    "dingtalk": "webhook",
    "feishu": "webhook",
    "wecom": "webhook",
    "telegram": "bot_token",
    "webhook": "url",
}

# 每个通道需要哪些环境变量，预检时提示用
ENV_HINTS = {
    "pushplus": "PUSHPLUS_TOKEN",
    "serverchan": "SERVERCHAN_SENDKEY",
    "bark": "BARK_KEY",
    "dingtalk": "DINGTALK_WEBHOOK",
    "feishu": "FEISHU_WEBHOOK",
    "wecom": "WECOM_WEBHOOK",
    "telegram": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID",
    "webhook": "CUSTOM_WEBHOOK",
}


def preflight(cfg) -> list:
    """检查推送通道配置。返回 [(标签, 状态, 说明)]，状态 ∈ ready / unconfigured / disabled。"""
    push_cfg = cfg.get("push") or {}
    rows = []
    for name in CHANNELS:
        ch = push_cfg.get(name) or {}
        label = CHANNEL_LABELS.get(name, name)
        if not ch.get("enabled"):
            rows.append((label, "disabled", ""))
            continue
        field = CRED_FIELDS.get(name, "")
        val = (ch.get(field) or "").strip()
        if not val:
            rows.append((label, "unconfigured",
                         f"未配置 —— 环境变量 {ENV_HINTS.get(name, field)} 为空"))
        else:
            rows.append((label, "ready", mask_secret(val)))
    return rows


def dispatch(cfg: dict, title: str, body: str, *, dry_run: bool = False):
    """向所有已启用通道推送。返回 [(通道名, 成功?, 详情)]"""
    push_cfg = cfg.get("push") or {}
    net = cfg.get("monitor") or {}
    kw = {
        "timeout": int(net.get("timeout_seconds", 25)),
        "proxy": net.get("proxy", "") or "",
        "insecure_ssl": bool(net.get("insecure_ssl", False)),
    }
    results = []
    if dry_run:
        log(f"[DRY-RUN] 不实际推送。标题：{title}")
        return results

    enabled_any = False
    for name, fn in CHANNELS.items():
        ch = push_cfg.get(name) or {}
        if not ch.get("enabled"):
            continue
        enabled_any = True
        try:
            ok, detail = fn(ch, title, body, **kw)
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        label = CHANNEL_LABELS.get(name, name)
        if ok is None:
            log(f"推送通道 [{label}] 跳过：{detail}", "WARN")
            results.append((label, None, detail))
        elif ok:
            log(f"推送通道 [{label}] 发送成功")
            results.append((label, True, detail))
        else:
            log(f"推送通道 [{label}] 发送失败：{detail}", "ERROR")
            results.append((label, False, detail))

    if not enabled_any:
        log("没有任何启用的推送通道，通知被丢弃（请在 config.json 的 push 里启用并填好凭据）", "WARN")
    return results


# ---------------------------------------------------------------- 状态文件


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"version": 1, "sources": {}, "sent": {}, "last_heartbeat": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        st.setdefault("version", 1)
        st.setdefault("sources", {})
        st.setdefault("sent", {})
        st.setdefault("last_heartbeat", "")
        return st
    except Exception as e:
        log(f"状态文件损坏，将重新建立基线：{e}", "WARN")
        return {"version": 1, "sources": {}, "sent": {}, "last_heartbeat": ""}


def save_state(path: str, state: dict) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    cutoff = time.time() - 7 * 86400
    state["sent"] = {k: v for k, v in (state.get("sent") or {}).items() if v > cutoff}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


# ---------------------------------------------------------------- 告警消息


def build_alert(level, src, strong_hits, ticket_items, other_items,
                new_sentences, page_url, cfg):
    notify = cfg.get("notify") or {}
    if level == "critical":
        head = notify.get("critical_title", "🚨 珠海航展门票开售信号！")
    else:
        head = notify.get("info_title", "📢 航展官网有更新")

    L = [f"**{head}**", ""]
    L.append(f"- **来源**：{src['name']}")
    L.append(f"- **时间**：{ts()}（北京时间）")
    L.append(f"- **页面**：[点此打开]({page_url})")

    if strong_hits:
        L += ["", "**命中开售关键词**"]
        for h in strong_hits[:4]:
            L.append(f"- `{'/'.join(h['words'])}` → {h['sentence']}")

    if ticket_items:
        L += ["", "**票务相关新公告**"]
        for it in ticket_items[:5]:
            L.append(f"- [{it['title']}]({it['url']})")

    if other_items:
        L += ["", "**其他新增公告**"]
        for it in other_items[:4]:
            L.append(f"- [{it['title']}]({it['url']})")

    if new_sentences and not strong_hits:
        L += ["", "**新增内容摘录**"]
        for s in new_sentences[:3]:
            L.append(f"> {s}")

    if level == "critical":
        L += ["", "---", "**官方购票渠道（务必走官方，谨防黄牛）**"]
        for i, c in enumerate(OFFICIAL_CHANNELS, 1):
            L.append(f"{i}. {c}")
        L += ["", "官方普通观众咨询：400-8800-113 / 0756-3375371"]

    return "\n".join(L)


# ---------------------------------------------------------------- 主流程


def check_source(src, cfg, state, baseline_mode):
    """检查单个监控源。返回 (alert_or_None, error_or_None)"""
    net = cfg.get("monitor") or {}
    kw_cfg = cfg.get("keywords") or {}
    positive = kw_cfg.get("positive") or []
    negative = kw_cfg.get("negative") or []
    ticket_title_kw = kw_cfg.get("ticket_title") or []

    url = src["url"]
    key = src.get("id") or url
    try:
        status, html, final_url = http_request(
            url,
            timeout=int(net.get("timeout_seconds", 25)),
            retries=int(net.get("retries", 3)),
            proxy=net.get("proxy", "") or "",
            insecure_ssl=bool(net.get("insecure_ssl", False)),
        )
    except Exception as e:
        return None, f"{src['name']} 抓取失败：{e}"

    text = html_to_text(html)
    text_norm = normalize_text(text)
    digest = sha1(text_norm)

    items = extract_items(
        html, final_url,
        url_pattern=src.get("item_url_pattern"),
        min_title_len=int(src.get("min_title_len", 8)),
    )
    sentences = split_sentences(text)
    # 去重并截断，避免状态文件膨胀
    uniq_sentences = list(dict.fromkeys(sentences))[:600]
    # 句子比对同样要抹掉日期/时间，否则页面上的日期刷新就会被当成「新增内容」
    # （正文 hash 已经归一化过，这里如果不对齐，两处判定会互相打架）
    uniq_sent_keys = [normalize_text(s) for s in uniq_sentences]

    prev = (state["sources"] or {}).get(key) or {}
    is_baseline = baseline_mode or (key not in (state["sources"] or {}))

    # 条目标题里常带发布日期（如「…最新消息\r\n 2026-09-11」），日期一变标题就变，
    # 会被误判成「新增公告」并反复告警。比对和去重签名统一用归一化后的标题，
    # 推送内容里仍然显示原始标题。
    for it in items:
        it["key"] = normalize_text(it["title"])

    prev_titles = set(prev.get("items") or [])
    prev_sentences = set(prev.get("sentences") or [])

    new_items = [] if is_baseline else [it for it in items if it["key"] not in prev_titles]
    new_sentences = [] if is_baseline else [
        s for s, k in zip(uniq_sentences, uniq_sent_keys) if k not in prev_sentences]

    # 部分源（如第三方聚合页）长期挂着固定的“购票渠道”文案，做关键词判定会误报，
    # 这类源用 keyword_scan=false 关掉关键词，只看“新增条目 / 内容变化”。
    if src.get("keyword_scan", True):
        hits = scan_keywords(text, positive, negative)
        strong_hits = [h for h in hits if not h["negated"]]
    else:
        hits, strong_hits = [], []

    ticket_items = [it for it in new_items if any(k in it["title"] for k in ticket_title_kw)]
    other_items = [it for it in new_items if it not in ticket_items]

    # 命中开售关键词时，把上下文句也带出来（含否定语境，便于人工判断）
    for h in hits:
        if h["negated"] and h["sentence"] not in new_sentences:
            new_sentences.append(h["sentence"])

    hash_changed = bool(prev.get("hash")) and prev["hash"] != digest
    notify_on_change = bool(src.get("notify_on_change", True))

    # ---- 判定告警级别
    level = None
    if strong_hits or ticket_items:
        level = "critical"
    elif notify_on_change and (new_items or new_sentences or hash_changed):
        level = "info"

    vlog(f"{src['name']}：HTTP {status}，正文 {len(text)} 字，条目 {len(items)}，"
         f"新条目 {len(new_items)}，新句子 {len(new_sentences)}，"
         f"关键词命中 {len(hits)}（其中非否定 {len(strong_hits)}），hash变更={hash_changed}")

    # ---- 更新状态（无论是否告警都要更新）
    state["sources"][key] = {
        "name": src["name"],
        "hash": digest,
        "items": [it["key"] for it in items][:200],
        "sentences": uniq_sent_keys,
        "checked_at": ts(),
    }

    if is_baseline:
        log(f"{src['name']}：建立基线（{len(items)} 个条目），本次不告警")
        return None, None

    if level is None:
        log(f"{src['name']}：无变化")
        return None, None

    # ---- 去重 / 冷却
    # 签名只能由「本次告警的证据」决定，不能用整页正文的 hash：
    # 聚合类页面的正文会频繁变动（推荐位轮换、CDN 缓存切换），
    # 拿整页 hash 当签名，同一条误报会反复突破去重、反复推送。
    sig_parts = sorted(it["key"] for it in new_items)
    sig_parts += sorted(h["sentence"] for h in strong_hits)
    if not sig_parts:
        sig_parts = new_sentences[:5]
    sig_src = "|".join(sig_parts)
    sig = f"{key}|{level}|{sha1(sig_src)[:16]}"
    sent = state["sent"]
    now_ts = time.time()
    if sig in sent:
        log(f"{src['name']}：同内容已推送过，跳过（级别 {level}）")
        return None, None
    if level == "info":
        cooldown = int((cfg.get("notify") or {}).get("change_cooldown_minutes", 360)) * 60
        last_info = float(prev.get("last_info_alert") or 0)
        if last_info and now_ts - last_info < cooldown:
            log(f"{src['name']}：info 级冷却中（{cooldown // 60} 分钟），跳过")
            return None, None
        state["sources"][key]["last_info_alert"] = now_ts
    sent[sig] = now_ts

    alert = {
        "level": level,
        "src": src,
        "strong_hits": strong_hits,
        "ticket_items": ticket_items,
        "other_items": other_items,
        "new_sentences": new_sentences[:5],
        "page_url": final_url,
    }
    return alert, None


def _build_summary(sources, state, errors, alerts, pushed, chan_rows, is_baseline) -> str:
    """生成 GitHub Actions 的 Job Summary（Markdown），运行页面上直接可见。"""
    err_names = set()
    for e in errors:
        err_names.add(e.split(" 抓取失败")[0].split(" 检查异常")[0])
    level_by_key = {}
    for a in alerts:
        level_by_key[a["src"].get("id") or a["src"]["url"]] = a["level"]

    lines = ["## 珠海航展门票监控 · 本轮结果", ""]
    lines.append(f"- **时间**：{ts()}（北京时间）")
    lines.append(f"- **监控源**：{len(sources) - len(errors)}/{len(sources)} 正常")
    lines.append(f"- **告警**：{len(alerts)} 条，已推送 {pushed} 条")
    if is_baseline:
        lines.append("- **模式**：首次运行 / 基线，本次刻意不发告警")

    lines += ["", "| 监控源 | 状态 | 已记录条目 |", "| --- | --- | --- |"]
    for src in sources:
        key = src.get("id") or src["url"]
        st = state["sources"].get(key) or {}
        if src["name"] in err_names:
            status = "❌ 抓取失败"
        elif level_by_key.get(key) == "critical":
            status = "🚨 **开售信号**"
        elif level_by_key.get(key) == "info":
            status = "📢 有更新"
        else:
            status = "✅ 无变化"
        lines.append(f"| {src['name']} | {status} | {len(st.get('items') or [])} |")

    ready = [r for r in chan_rows if r[1] == "ready"]
    unconf = [r for r in chan_rows if r[1] == "unconfigured"]
    lines += ["", "### 推送通道", ""]
    lines.append("已就绪：" + ("、".join(r[0] for r in ready) if ready else "**无**"))
    if unconf:
        lines.append("")
        lines.append("启用了但缺凭据：" + "、".join(f"{r[0]}" for r in unconf))
    return "\n".join(lines)


def run_once(cfg, *, dry_run=False, baseline=False) -> int:
    net = cfg.get("monitor") or {}
    state_path = resolve_path(net.get("state_file", "state/state.json"))
    state = load_state(state_path)
    first_run = not os.path.exists(state_path)

    # ---- 推送通道预检：没通道 = 监控白跑，必须让用户立刻看见
    chan_rows = preflight(cfg)
    ready = [r for r in chan_rows if r[1] == "ready"]
    unconfigured = [r for r in chan_rows if r[1] == "unconfigured"]
    log("推送通道检查：")
    if not any(r[1] != "disabled" for r in chan_rows):
        log("  ⚠️ 所有通道都是关闭状态（config.json 的 push 里没有 enabled=true）", "WARN")
    for label, status, detail in chan_rows:
        if status == "ready":
            log(f"  ✅ {label}：{detail}")
        elif status == "unconfigured":
            log(f"  ⚠️ {label}：{detail}", "WARN")

    # 没通道时的失败要「推迟到检查结束再退出」：如果立刻 return，
    # 状态文件就不会更新，等用户补上 token 后，积压了几天的变化会被一次性
    # 当成新公告推出来。所以先照常抓取、照常更新状态，最后再让任务变红。
    push_blocked = False
    if not ready:
        # 提示信息要跟着运行环境走，否则在服务器上会给出让人莫名其妙的 GitHub 指引
        if os.environ.get("GITHUB_ACTIONS") == "true":
            fix_hint = ("  1) 到 GitHub 仓库 Settings → Secrets and variables → Actions 添加 "
                        "PUSHPLUS_TOKEN（值填 PushPlus 的 token）；\n"
                        "  2) 或在 config.json 的 push 里启用并填写任意一个通道的凭据。")
            where = "GitHub 的失败提醒"
        else:
            fix_hint = ("  1) 把凭据写进本目录的 local.env，格式：PUSHPLUS_TOKEN=你的token\n"
                        "     （服务器上即 /opt/airshow-monitor/local.env，写完执行 "
                        "systemctl start airshow-monitor.service 立即验证）\n"
                        "  2) 或 export 该环境变量 / 改 config.json 的 push 段。")
            where = "systemd 的失败记录"
        msg = ("没有任何可用的推送通道，即使发现开售也无法通知到你。\n"
               "  修复方式：\n" + fix_hint)
        log(msg, "ERROR")
        write_step_summary(
            "## ❌ 监控未生效：没有可用的推送通道\n\n"
            "即使现在门票开售，程序也无法通知你。\n\n"
            "**修复方式（二选一）**\n\n"
            "1. 到 `Settings → Secrets and variables → Actions` 添加名为 "
            "`PUSHPLUS_TOKEN` 的 Secret，值填 PushPlus 的 token\n"
            "2. 或修改 `config.json`，启用并填写任意一个通道的凭据\n\n"
            "| 通道 | 状态 |\n| --- | --- |\n"
            + "\n".join(f"| {l} | {d if s == 'unconfigured' else ('已就绪' if s == 'ready' else '未启用')} |"
                        for l, s, d in chan_rows if s != "disabled")
            + "\n"
        )
        if not (cfg.get("notify") or {}).get("require_push_channel", True) or dry_run:
            log("（require_push_channel 为 false，继续检查页面但本轮不推送）", "WARN")
        else:
            # 让任务变红是为了让你注意到，但不能每 10 分钟红一次 —— 那样
            # GitHub 的失败邮件会把你淹没。所以 24 小时内只红一次。
            last_warn = float(state.get("push_warning_at") or 0)
            if time.time() - last_warn > 86400:
                state["push_warning_at"] = time.time()
                push_blocked = True
                log(f"检查结束后本次会以失败退出，以便你注意到这个问题（{where}）。"
                    f"24 小时内不会重复报错，避免刷屏。", "ERROR")
            else:
                log("24 小时内已就该问题提醒过，本次只记录日志、不让任务变红。", "WARN")

    if baseline or first_run:
        log("=" * 62)
        log("首次运行 / 基线模式：只记录当前页面状态，不发送告警。")
        log("这样能避免把「页面本来就有的内容」误判成新消息。")
        log("=" * 62)

    sources = [s for s in (cfg.get("sources") or []) if s.get("enabled", True)]
    if not sources:
        log("配置里没有启用任何监控源", "ERROR")
        return 1

    alerts, errors = [], []
    for src in sources:
        try:
            alert, err = check_source(src, cfg, state, baseline or first_run)
        except Exception as e:
            alert, err = None, f"{src.get('name', src.get('url'))} 检查异常：{type(e).__name__}: {e}"
        if err:
            errors.append(err)
            log(err, "ERROR")
        if alert:
            alerts.append(alert)

    save_state(state_path, state)

    # critical 优先
    alerts.sort(key=lambda a: 0 if a["level"] == "critical" else 1)
    max_push = int((cfg.get("notify") or {}).get("max_push_per_run", 3))
    to_push = alerts[:max_push]
    if len(alerts) > max_push:
        log(f"本轮共 {len(alerts)} 条告警，按上限只推送前 {max_push} 条", "WARN")

    prefix = (cfg.get("notify") or {}).get("title_prefix", "珠海航展")
    pushed = 0
    for a in to_push:
        title = ("🚨 " if a["level"] == "critical" else "📢 ") + prefix + "：" + a["src"]["name"]
        if a["level"] == "critical":
            title = "🚨 " + prefix + "门票开售信号！"
        body = build_alert(a["level"], a["src"], a["strong_hits"], a["ticket_items"],
                           a["other_items"], a["new_sentences"], a["page_url"], cfg)
        log("-" * 62)
        log(f"触发 {a['level'].upper()} 告警：{a['src']['name']}")
        log(body)
        res = dispatch(cfg, title, body, dry_run=dry_run)
        if any(ok for _, ok, _ in res):
            pushed += 1

    # 心跳：确认程序还活着
    hb = cfg.get("heartbeat") or {}
    if hb.get("enabled") and not dry_run and not baseline:
        today = now_cst().strftime("%Y-%m-%d")
        if (now_cst().hour == int(hb.get("hour_cst", 10))
                and state.get("last_heartbeat") != today):
            ok_src = len(sources) - len(errors)
            body = (f"**监控心跳 {today}**\n\n"
                    f"- 监控源：{ok_src}/{len(sources)} 正常\n"
                    f"- 本轮告警：{len(alerts)} 条\n"
                    f"- 状态：程序运行正常，门票仍未发现开售信号\n")
            dispatch(cfg, f"✅ {prefix}监控运行中", body, dry_run=False)
            state["last_heartbeat"] = today
            save_state(state_path, state)

    log("=" * 62)
    log(f"本轮完成：监控源 {len(sources)} 个，成功 {len(sources) - len(errors)} 个，"
        f"告警 {len(alerts)} 条，实际推送 {pushed} 条")

    if errors:
        for e in errors:
            log(f"  ✗ {e}", "WARN")

    write_step_summary(_build_summary(sources, state, errors, alerts, pushed,
                                      chan_rows, baseline or first_run))

    # 全部源都失败 -> 返回非 0，让 GitHub Actions 变红，便于及时发现
    if len(errors) == len(sources):
        log("所有监控源都抓取失败，请检查网络 / 代理配置", "ERROR")
        return 1
    if push_blocked:
        log("本轮以失败退出：没有可用的推送通道（详见上面的修复方式）", "ERROR")
        return 1
    return 0


def test_push(cfg) -> int:
    prefix = (cfg.get("notify") or {}).get("title_prefix", "珠海航展")

    # 先做预检，把“哪个通道缺什么”直接打在日志里
    chan_rows = preflight(cfg)
    ready = [r for r in chan_rows if r[1] == "ready"]
    unconf = [r for r in chan_rows if r[1] == "unconfigured"]
    log("推送通道检查：")
    for label, status, detail in chan_rows:
        if status == "ready":
            log(f"  ✅ {label}：{detail}")
        elif status == "unconfigured":
            log(f"  ⚠️ {label}：{detail}", "WARN")
    if not ready:
        log("没有任何已就绪的推送通道，测试无法进行。\n"
            "  到 GitHub 仓库 Settings → Secrets and variables → Actions 添加 "
            "PUSHPLUS_TOKEN，或在 config.json 的 push 里填写任意一个通道的凭据。", "ERROR")
        write_step_summary(
            "## ❌ 测试推送失败：没有可用的推送通道\n\n"
            + "\n".join(f"- **{l}**：{d}" for l, s, d in chan_rows if s == "unconfigured")
            + "\n\n请到 `Settings → Secrets and variables → Actions` 添加 "
              "`PUSHPLUS_TOKEN`（值填 PushPlus 的 token）。\n"
        )
        return 1

    body = (
        "**这是一条测试推送**\n\n"
        "如果你在手机上看到这条消息，说明推送通道已经打通 ✅\n\n"
        f"- 时间：{ts()}（北京时间）\n"
        "- 程序：2026 珠海航展门票开售监控\n"
        "- 下一步：之后每 10 分钟自动检查一次，发现开售立刻通知你\n"
    )
    res = dispatch(cfg, f"✅ {prefix}监控 · 测试推送", body, dry_run=False)
    if not res:
        log("没有任何启用的推送通道。请在 config.json 的 push 中启用通道并填写凭据。", "ERROR")
        return 1
    ok = [r for r in res if r[1] is True]
    bad = [r for r in res if r[1] is False]
    log(f"测试完成：成功 {len(ok)} 个，失败 {len(bad)} 个，"
        f"跳过 {len(res) - len(ok) - len(bad)} 个")

    if ok:
        write_step_summary(
            "## ✅ 测试推送成功\n\n"
            f"已发送到：{'、'.join(r[0] for r in ok)}\n\n"
            "请检查手机是否收到消息。收到即表示监控链路已完全打通。\n"
        )
    else:
        write_step_summary(
            "## ❌ 测试推送失败\n\n"
            + "\n".join(f"- **{r[0]}**：{r[2]}" for r in bad)
            + "\n\n凭据已注入但发送被拒绝，通常是 token 填错或已失效。\n"
        )
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI


def main(argv=None) -> int:
    global VERBOSE, _LOG_FH
    ap = argparse.ArgumentParser(
        description="2026 珠海航展（第十六届中国航展）门票开售监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--config", default=os.path.join(BASE_DIR, "config.json"),
                    help="配置文件路径（默认 config.json）")
    ap.add_argument("--once", action="store_true", help="跑一轮检查（默认行为）")
    ap.add_argument("--test-push", action="store_true", help="只发一条测试推送")
    ap.add_argument("--dry-run", action="store_true", help="只检查并打印，不推送")
    ap.add_argument("--baseline", action="store_true", help="只建立基线，不告警")
    ap.add_argument("--reset", action="store_true", help="删除状态文件后重建基线")
    ap.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = ap.parse_args(argv)

    VERBOSE = args.verbose
    cfg = load_config(args.config)

    net = cfg.get("monitor") or {}
    log_file = resolve_path(net.get("log_file", ""))
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        _LOG_FH = open(log_file, "a", encoding="utf-8")

    try:
        if args.reset:
            state_path = resolve_path(net.get("state_file", "state/state.json"))
            if os.path.exists(state_path):
                os.remove(state_path)
                log(f"已删除状态文件：{state_path}")
            return run_once(cfg, dry_run=args.dry_run, baseline=True)

        if args.test_push:
            return test_push(cfg)

        return run_once(cfg, dry_run=args.dry_run, baseline=args.baseline)
    finally:
        if _LOG_FH:
            _LOG_FH.close()


if __name__ == "__main__":
    sys.exit(main())
