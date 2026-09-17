# 2026 珠海航展门票开售监控

盯着**第十六届中国航展（2026 珠海航展）**的官方渠道，一旦发现普通观众门票开售的苗头，**立刻推送到你手机微信**。

- 纯 Python 标准库，**零第三方依赖**，不需要装任何包
- 跑在 GitHub Actions 上，**7×24 小时、每 10 分钟检查一次**，不用开电脑
- 自动区分「真的开售了」和「官方辟谣说还没开售」，不瞎报

---

## 一、先搞清楚现在的状况

| 项目 | 情况 |
| --- | --- |
| 展会 | 第十六届中国国际航空航天博览会 |
| 时间 | **2026 年 12 月 7 日 – 13 日** |
| 地点 | 珠海国际航展中心 |
| 门票状态 | **截至 2026-09-15 仍未开售** |
| 官方口径 | 票价、销售规则、开售时间、购票渠道**全部未发布**，尚未启动任何售票工作；网传「内部票」「低价票」「提前预售」**均为虚假宣传** |
| 预计节点 | **2026 年 10 月**统一官宣全部票务方案 |
| 官方咨询 | 400-8800-113 / 0756-3375371 |

**官方购票渠道只有这 4 个，其它一律别信：**

1. 「中国国际航空航天博览会」官方网站（`www.airshow.com.cn` / `piao.airshow.com.cn`）
2. 「中国航展」微信公众号
3. 「珠海航展」微信小程序
4. 「珠海航展」APP

> 所以这个程序的定位是**抢时间差**：官方一发布公告，你比别人早知道十几分钟，够你从容打开官方渠道下单。它不抢票、不刷接口、不碰任何非官方渠道。

---

## 二、快速上手

### 第 1 步：拿到微信推送的 token（约 1 分钟）

1. 手机微信打开 <https://www.pushplus.plus/>，微信扫码登录
2. **完成实名认证**（个人中心里）
3. 点「一对一推送」，复制那串 **token**
4. 关注它提示的公众号（消息从那里进来）

> ⚠️ **第 2 步的实名认证千万别跳过。** PushPlus 未实名时**不能发消息**，而且它返回的报错是
> `code 903 用户令牌不正确`——**把「没实名」误导成「token 错了」**。照着教程配的人几乎都会卡在这里，
> 反复重新复制 token 却怎么都不对。遇到 903，先查实名状态，再查 token 值。

> 为什么用 PushPlus 而不是 Server酱？PushPlus 免费版每天 200 条，Server酱免费版只有约 5 条，监控类程序容易把额度用完。两个都支持，配置里换一下就行。

### 第 2 步：建仓库、传文件（约 1 分钟）

1. 在 GitHub 新建一个仓库，**建议选 Public**（公开仓库的 Actions 分钟数完全免费、不限量）
2. 把**本目录下的所有文件和文件夹**传到仓库根目录

   ⚠️ 注意 `.github` 这个文件夹必须一起传上去，定时任务就靠它。用网页上传时，如果拖文件夹不方便，可以用命令行：

   ```bash
   cd "/Users/macos/WorkBuddy AI/2026-09-17-15-01-19/zhuhai-airshow-ticket-monitor"
   git init && git add -A
   git commit -m "珠海航展门票监控"
   git branch -M main
   git remote add origin https://github.com/你的用户名/仓库名.git
   git push -u origin main
   ```

### 第 3 步：把 token 填进 Secrets（约 30 秒）

仓库页面 → **Settings** → 左侧 **Secrets and variables** → **Actions** → **New repository secret**

- Name 填：`PUSHPLUS_TOKEN`
- Secret 填：刚才复制的 token

> token 只存在 GitHub 的加密 Secrets 里，不会写进代码，公开仓库也看不到。

### 第 4 步：开启并测试（约 30 秒）

1. 仓库页面点 **Actions** 标签，如果提示需要启用工作流，点一下允许
2. 左侧选「**珠海航展门票监控**」→ 右侧 **Run workflow** 按钮
3. 勾选 **test_push**，然后点绿色 **Run workflow**
4. 等十几秒，**手机上应该收到一条测试消息** ✅

收到测试消息就说明全线打通了。之后它每 10 分钟自动跑一次，你什么都不用管。

### 第 5 步：配置定时触发（**必做**，别跳过）

⚠️ **GitHub 自带的 `schedule` 定时器并不可靠**——尤其在新建仓库上。本项目实测：
仓库建好后近 4 小时、20 多次 cron 机会**一次都没触发**，而手动运行完全正常。
这不是配置错误，是 GitHub 侧的问题（新仓库的 schedule 注册可能长期不生效）。

所以用**外部 cron 服务**来定时调用 GitHub 的接口，这才是可靠的方案。

#### 5.1 创建一个 PAT（个人访问令牌）

1. 打开 <https://github.com/settings/personal-access-tokens/new>
2. **Token name** 填 `airshow-monitor-cron`
3. **Expiration** 选 90 天或更长（过期后定时任务会失败，记得续期）
4. **Repository access** → 选 **Only select repositories** → 勾上 `xu810201/airshow-ticket`
5. **Permissions** → 展开 **Repository permissions** → 找到 **Actions** → 设为 **Read and write**
6. 点 **Generate token**，复制那串 `github_pat_...`（**离开页面就再也看不到了**）

#### 5.2 先本地验证 PAT 能用

```bash
cd zhuhai-airshow-ticket-monitor
python3 trigger-workflow.py
```

粘贴 PAT（不回显），它会明确告诉你结果：

| 输出 | 含义 |
| --- | --- |
| `✅ 成功（GitHub 返回 204）` + 新运行号 | PAT 可用，继续下一步 |
| `❌ 403 权限不足` | Actions 权限没设成 Read and write |
| `❌ 404 找不到` | PAT 没授权访问这个仓库 |
| `❌ 401 未认证` | PAT 复制错了或已过期 |

#### 5.3 在 cron-job.org 建任务

1. 注册 <https://cron-job.org/>（免费，需邮箱验证）
2. **Console** → **Create cronjob**
3. 按下表填：

| 字段 | 填什么 |
| --- | --- |
| **Title** | 珠海航展门票监控 |
| **URL** | `https://api.github.com/repos/xu810201/airshow-ticket/actions/workflows/monitor.yml/dispatches` |
| **Schedule** | Every 10 minutes（免费版最小可到 1 分钟） |
| **Request method** | **POST** |
| **Request body** | `{"ref":"main"}` |

4. 再添加 **3 个自定义请求头**（点 **Add header**）：

| Header | Value |
| --- | --- |
| `Authorization` | `Bearer 你的PAT` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |

5. 保存，**并勾选失败邮件通知**（Enable e-mail notification on failure）

> ⚠️ **两个必须知道的坑**
> - cron-job.org 对**连续失败 25 次的任务会自动停用**。PAT 过期、仓库改名都会导致失败，
>   所以失败邮件通知一定要开，否则任务停了你还不知道。
> - 它不支持自定义 `User-Agent` 和 `Connection` 请求头，会自动忽略——不影响本任务。

#### 5.4 验证

等 10 分钟，打开 <https://github.com/xu810201/airshow-ticket/actions>，
运行记录里应该多出一条（事件类型是 `workflow_dispatch`，因为是走 API 触发的）。
之后每 10 分钟就会自动多一条。

确认正常后，可以把诊断用的 `cron-test.yml` 删掉：

```bash
git rm .github/workflows/cron-test.yml && git commit -m "移除诊断工作流" && git push
```

> 💡 **如果你自己有常开的 Linux 服务器**，可以完全跳过上面这一整套（PAT、cron-job.org 都不需要），
> 直接用 systemd 定时器跑，最省事也最可靠——见 **[十、部署到自己的 Linux 服务器](#十部署到自己的-linux-服务器最稳的方案)**。

---

## 三、它在盯哪些页面

| 监控源 | 地址 | 为什么盯它 |
| --- | --- | --- |
| 官网公告栏 | `airshow.com.cn/Category_128/` | **最核心的信号源**。票务方案会以公告形式发布，这是服务端渲染页面，抓取最稳 |
| 官网门票信息页 | `airshow.com.cn/Category_1205/` | 「普通观众 → 门票信息」栏目，开售后这里会填上票价和购票须知。**现在是空的，本身就是「未开售」的证据** |
| 官网首页 | `airshow.com.cn` | 重大消息会上首页头条 / 轮播 |
| 官网新闻媒体 | `airshow.com.cn/Category_1132/` | 新闻口径往往比公告更早、更口语化 |
| 官方票务站 | `piao.airshow.com.cn` | 真正的购票入口，页面一变就说明有动作 |
| 珠海本地宝 | `m.zh.bendibao.com/...` | 第三方聚合页，官方有动静它通常几分钟内就更新，作为交叉验证 |

> 关于 `piao.airshow.com.cn`：它是一个 Vue 单页应用，静态 HTML 里没有正文内容，所以**没法靠抓它判断开售**，只能当「页面有没有改版」的辅助信号。这也是为什么本程序把官网公告栏当主信号源。

---

## 四、怎么判定「真的开售了」

程序不是简单搜关键词，那样会被官方辟谣文案骗到。它做三层判断：

**第 1 层 · 关键词 + 否定语境**

逐句扫描。句子命中「开售 / 开始售票 / 售票时间 / 购票入口 / 票务方案 / 票价公布……」等词，**并且同一句里没有**「暂未开售 / 尚未启动 / 均不实 / 辟谣 / 谨防 / 黄牛」这类否定词，才算真信号。

所以这两句的处理完全不同：

- ❌ `第十六届中国航展门票暂未开售，预计10月公布售票时间。` → 命中「售票时间」但同时命中「暂未」，**判定为否定，不告警**
- ✅ `第十六届中国航展普通观众门票将于10月15日10:00正式开售，购票通道同步开放。` → **立刻告警**

**第 2 层 · 新增公告标题**

官网每条公告都有独立的 `/Item/xxxxx.aspx` 地址。程序记录已见过的公告标题，一旦出现新的、且标题里带「门票 / 票务 / 购票 / 售票 / 票价 / 预售」的公告，直接按最高级别告警。

**第 3 层 · 页面内容变化**

没命中关键词、但页面确实新增了内容（比如多了一条无关公告），推一条**普通级别**的提醒，附带新增内容摘录。这类提醒同一来源 6 小时内不会重复推，不会刷屏。

**防误报设计**：首次运行只建立基线、不发任何通知；日期和时间会被归一化（`2026-09-17` → `<DATE>`），所以页面上的日期刷新不会造成误报。

---

## 五、配置说明（`config.json`）

改完直接提交，GitHub 下一轮就生效。

```jsonc
{
  "notify": {
    "change_cooldown_minutes": 360,   // 普通提醒的冷却时间（分钟）
    "max_push_per_run": 3,            // 单轮最多推几条，防轰炸
    "require_push_channel": true      // 没有任何可用推送通道时报错退出，避免“假装在跑”
  },
  "heartbeat": {
    "enabled": false,                 // 改成 true，每天 10:00 发一条“我还活着”
    "hour_cst": 10
  },
  "monitor": {
    "proxy": "",                      // 云端抓不动国内站点时填代理
    "insecure_ssl": false             // 极少数站点证书链不全时才开
  }
}
```

**换推送渠道**：把对应通道的 `enabled` 改成 `true`，填好凭据即可，可以同时开多个。

| 通道 | 需要什么 | 备注 |
| --- | --- | --- |
| `pushplus` | token | **推荐**，微信收，免费 200 条/天 |
| `serverchan` | SendKey | 微信收，免费版仅约 5 条/天 |
| `bark` | 设备 Key | iPhone，免费无延迟，最稳 |
| `dingtalk` / `feishu` / `wecom` | 机器人 Webhook | 拉个只有自己的群，发到群里 |
| `telegram` | Bot Token + chat_id | 适合海外 |
| `webhook` | 自定义地址 | 转发到自建服务 / n8n / IFTTT |

**加监控源**：往 `sources` 数组里加一项即可。

```jsonc
{
  "id": "my_source",                 // 唯一标识，改了会重新建基线
  "name": "显示在通知里的名字",
  "url": "https://...",
  "item_url_pattern": "/Item/",      // 可选：只把匹配的链接当“公告条目”
  "keyword_scan": true,              // 可选：false = 不参与关键词判定
  "notify_on_change": true,          // 可选：页面有变化就推一条
  "enabled": true
}
```

> `keyword_scan: false` 是给第三方聚合页用的——那种页面常年挂着「购票入口：①②③④」的固定文案，做关键词判定会天天误报。

> ⚠️ **`item_url_pattern` 不是可选项，是防误报的关键。** 不填的话，页面上**每一个链接**都会被视为
> “公告条目”，包括导航菜单、栏目入口、备案号、甚至内联 JS 被误当成 `<a>` 的碎片。
> 实测踩过的坑：珠海本地宝的栏目入口标题叫「第十六届中国航展门票」，指向目录式链接
> `/xiuxian/zhhzmp/`，标题里带「门票」二字 —— 它被当成「新增票务公告」，
> **直接触发最高级开售告警**，而且因为页面会缓存切换、正文 hash 反复变化，这条误报会反复推送。
>
> 判定规则很简单：**先看这个页面上的真实文章长什么样**，用 URL 特征把它们圈出来。
>
> | 站点类型 | 真实文章的 URL 特征 | 建议正则 |
> | --- | --- | --- |
> | ASP.NET 官网公告栏 | `/Item/14509.aspx` | `/Item/` |
> | 本地宝这类聚合站 | `/xiuxian/106024.shtm` | `\\.shtm$` |
> | 没有文章列表的栏目页 | —— | 填一个匹配不到的正则（如 `/Item/`），让它只做「内容变化」检测 |
>
> 验证方法：改完正则跑一次，看日志里「建立基线（N 个条目）」的 N 是不是等于页面上真实文章数。
> 数字明显偏大，就是混进了导航项。

---

## 六、本地跑（可选）

```bash
cd zhuhai-airshow-ticket-monitor
python3 check-push.py          # 【首选】本地秒级诊断 token 是否有效，不经过 GitHub
./run-local.sh --test-push     # 测推送能不能收到（需要先 export PUSHPLUS_TOKEN）
./run-local.sh                 # 检查一轮
./run-local.sh --dry-run -v    # 只看结果不推送，带详细日志
./run-local.sh --reset         # 清空状态，重新建立基线
python3 selftest.py            # 跑判定逻辑自测（不联网）
```

**推送失败时的排查顺序**：先跑 `python3 check-push.py`。它会把 token 直接发给 PushPlus 官方接口，
几秒钟告诉你到底是哪一类问题——比在 GitHub 上来回试快得多：

| 返回 | 含义 | 怎么办 |
| --- | --- | --- |
| `code 200` | token 有效，请求已受理 | 若微信没收到，检查是否已关注「pushplus 推送加」公众号 |
| `code 903 用户令牌不正确` | **大概率是账号未实名认证**，其次是 token 复制错 | 先到 pushplus.plus 个人中心完成**实名认证**，再检查 token 值 |

想在本机常驻，用附带的 launchd 配置（把里面的路径改成你的真实路径）：

```bash
cp com.zhuhai.airshow.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.zhuhai.airshow.monitor.plist
```

**本机方案的短板**：电脑关机、合盖休眠、断网时都不监控。所以主方案还是 GitHub Actions。

---

## 七、常见问题

**Q：GitHub 自带的定时任务根本没跑起来？**
**这是已知问题，直接用外部 cron 兜底，见「第 5 步：配置定时触发」。** 实测新建仓库近 4 小时、20 多次
cron 机会一次都没触发，而手动运行完全正常——排查过仓库可见性、fork 状态、工作流 state、账号年龄、
默认分支、Actions 页面告警，全部正常，就是 GitHub 侧不触发。外部 cron 服务没有这个问题。

**Q：GitHub 定时任务准吗？**
免费版的 cron 在高峰期可能延迟几分钟到十几分钟，这是 GitHub 的调度特性，不是程序问题。
用外部 cron 服务（第 5 步）可以规避。

**Q：会不会过一阵子自己停了？**
GitHub 有个规则：仓库 **60 天没有任何活动**，定时任务会被自动停用，并给你发邮件。收到邮件点一下启用就行；或者随便提交一次改动。本项目持续到 12 月，期间正常不会触发。

**Q：私有仓库会不会超额？**
私有仓库每月 2000 分钟免费额度。每 10 分钟一次 ≈ 4320 次/月，每次计费约 1 分钟 → 约 4320 分钟，**会超**。两个办法：① 仓库设为 **Public**（Actions 完全免费）；② 把 `.github/workflows/monitor.yml` 里的 `*/10` 改成 `*/30`，降到约 1440 分钟/月。

**Q：手机上收不到消息？**
先手动触发一次 `workflow_dispatch` 并勾选 `test_push`。如果 Actions 日志里显示发送成功但手机没收到，检查公众号是否已关注、微信是否屏蔽了服务通知。日志里每个通道的成败和原因都会打印出来。

**Q：为什么日志说「跳过：未配置」？**
某个通道 `enabled: true` 但凭据是空的。要么填上凭据，要么把它改成 `false`。这不会影响其它通道。

**Q：日志报 `code=903 用户令牌不正确`，token 我反复核对过没错啊？**
**先查 PushPlus 账号有没有完成实名认证。** 未实名时 PushPlus 不允许发消息，但它返回的报错是
「用户令牌不正确」——把「没实名」说成了「token 错」，极具误导性。到 <https://www.pushplus.plus/>
登录后在个人中心完成实名认证即可。确认已实名后，再去查 token 值本身。

**Q：任务变红了，是坏了吗？**
不一定是坏事，红色的含义只有两种，运行页面顶部的 **Summary** 会直接告诉你原因：

- **❌ 监控未生效：没有可用的推送通道** —— 说明 `PUSHPLUS_TOKEN` 没配上或填错了。这是刻意设计的：宁可报错也不能让监控悄悄跑着却永远发不出通知。**为避免每 10 分钟红一次刷爆你的邮件，这个问题 24 小时内只会让任务变红一次**，其余轮次只记录日志。配好 token 即恢复绿色。
- **抓取失败** —— GitHub 服务器访问国内站点偶尔超时。程序自带 3 次重试；如果持续失败，在 `config.json` 的 `monitor.proxy` 里填代理。

**Q：怎么看每次检查的结果？**
不用翻日志。每次运行结束后，Actions 运行页面上会直接显示一张 **Job Summary** 表格，列出每个监控源的状态（✅ 无变化 / 📢 有更新 / 🚨 开售信号 / ❌ 抓取失败）、已记录的公告条数、以及推送通道是否就绪。

---

## 八、重要提醒

- **只走上面那 4 个官方渠道购票。** 官方已明确：不存在任何内部购票、提前锁票的特殊渠道。
- 不要相信「内部票」「低价票」「提前预售」，不要私下转账。通过非正规渠道购票极易遭遇假票、诈骗、溢价，以及无法核验入场。
- 本程序**只做信息监控和通知**，不代购、不抢票、不触碰任何非官方接口，也不收集你的任何个人信息。

---

## 九、文件清单

| 文件 | 作用 |
| --- | --- |
| `monitor.py` | 主程序，抓取 + 判定 + 推送 |
| `config.json` | 配置文件：监控源、关键词、推送通道 |
| `selftest.py` | 判定逻辑自测，5 个场景，不联网 |
| `check-push.py` | PushPlus token 本地诊断，秒级定位推送失败原因 |
| `trigger-workflow.py` | 验证 PAT 并触发云端工作流（外部 cron 兜底方案配套） |
| `.github/workflows/monitor.yml` | GitHub Actions 定时任务（每 10 分钟）。用 `checkout@v7` / `setup-python@v7` / `cache@v6`，均为 Node 24 运行时，不会有弃用告警 |
| `.github/workflows/cron-test.yml` | 诊断用：验证 GitHub 的 `schedule` 触发器到底会不会响，确认后可删 |
| `run-local.sh` | 本地运行脚本，自动读取同目录的 `local.env` 获取凭据 |
| `deploy-server.sh` | 一条命令把最新代码同步到 Linux 服务器（`/opt/airshow-monitor`），并做语法自检 |
| `set-token.sh` | 把 PushPlus token 安全写入服务器 `local.env` 并立即验证（输入不回显） |
| `check-status.sh` | 一键判断服务器上的监控是否真的在正常工作（9 项检查 + 结论） |
| `com.zhuhai.airshow.monitor.plist` | 可选的 macOS 本机定时任务（另一种兜底） |
| `local.env` | 本机凭据（`PUSHPLUS_TOKEN=...`），已 gitignore，不会提交 |
| `state/` | 运行状态（已看过的公告和句子），已加入 .gitignore |
| `requirements.txt` | 空的——本项目零依赖 |

---

## 十、部署到自己的 Linux 服务器（最稳的方案）

**适合谁**：你有一台常年开机的 Linux 服务器（NAS、小主机、云服务器都行）。
**好处**：不用 PAT、不用 cron-job.org、不用管 GitHub 的 schedule 靠不靠谱，
systemd 的定时器是本地触发的，准时且不会「被静默停用」。

以下命令里的 `192.168.0.10`、`root`、`~/.ssh/bomweb_ubuntu` 请换成你自己的。

### 10.1 服务器需要什么

只要两样：**Python 3.8+**（只用到标准库，不用装任何 pip 包）和 **systemd**。
Debian / Ubuntu / CentOS / 群晖等都能直接跑。

```bash
ssh root@192.168.0.10 "python3 -V && systemctl --version | head -1"
```

### 10.2 建目录和两个 systemd 单元

```bash
ssh root@192.168.0.10 "mkdir -p /opt/airshow-monitor/state"
```

`/etc/systemd/system/airshow-monitor.service`：

```ini
[Unit]
Description=珠海航展门票开售监控（单次检查）
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/airshow-monitor
EnvironmentFile=-/opt/airshow-monitor/local.env
ExecStart=/usr/bin/python3 /opt/airshow-monitor/monitor.py --once
TimeoutStartSec=300
```

> `EnvironmentFile=` 前面那个 **减号**不能去掉：它表示「文件不存在也不算错」，
> 否则你还没建 `local.env` 时服务会直接起不来。

`/etc/systemd/system/airshow-monitor.timer`：

```ini
[Unit]
Description=每 10 分钟检查一次珠海航展门票

[Timer]
OnBootSec=3min
OnCalendar=*:0/10
Persistent=true
AccuracySec=30s
RandomizedDelaySec=20

[Install]
WantedBy=timers.target
```

`Persistent=true` 保证服务器重启或休眠错过的班次会在开机后补跑一次；
`RandomizedDelaySec` 是给目标站点留点余地，避免每次都掐着整点打。

```bash
ssh root@192.168.0.10 "systemctl daemon-reload && systemctl enable --now airshow-monitor.timer"
```

### 10.3 写凭据（**关键，别漏**）

最省事的方式是在本地项目目录执行：

```bash
./set-token.sh
```

它会提示你粘贴 token（**输入时不回显**，也不经过命令行参数），自动去掉复制时多带的空格/换行，
写到服务器的 `local.env` 并把权限设成 600，然后**立刻在服务器上验证**——
验证通过才会触发一次完整检查，并给你微信发一条测试消息。

也可以手动写：

```bash
ssh root@192.168.0.10 "cat > /opt/airshow-monitor/local.env" <<'EOF'
PUSHPLUS_TOKEN=你的token
EOF
ssh root@192.168.0.10 "chmod 600 /opt/airshow-monitor/local.env"
```

写完立刻手动跑一次验证：

```bash
ssh root@192.168.0.10 "systemctl start airshow-monitor.service; journalctl -u airshow-monitor.service -n 15 --no-pager"
```

看到 `本轮完成：监控源 6 个，成功 6 个` 就是通了。

> 如果日志里出现 `⚠️ PushPlus（微信）：未配置 —— 环境变量 PUSHPLUS_TOKEN 为空`，
> 说明这一步还没做。程序发现「没有任何推送通道」时会明确报错，
> 但同一条提醒 **24 小时内只报一次**，避免每 10 分钟刷一条。

### 10.4 以后更新代码

在本地项目目录执行：

```bash
./deploy-server.sh            # 同步代码 + 语法自检
./deploy-server.sh --restart  # 同步后立刻跑一次
```

它只覆盖代码，**不会动**服务器上的 `local.env`（凭据）和 `state/`（已看过的公告记录），
所以反复部署不会导致重复推送。

如果服务器地址或密钥不一样，用环境变量覆盖：

```bash
AIRSHOW_HOST=deploy@10.0.0.5 AIRSHOW_KEY=~/.ssh/id_ed25519 ./deploy-server.sh
```

### 10.5 怎么确认部署成功（一条命令）

```bash
./check-status.sh
```

它会逐项检查并给出明确结论，比如：

```
检查 root@192.168.0.10:/opt/airshow-monitor

  ✅ 能连上服务器
  ✅ 定时器已设为开机自启
  ✅ 定时器正在运行
  ✅ 下一次自动运行：Thu 2026-09-17 21:40:11 CST
  ✅ 累计运行过 9 次，最近一次：Thu 2026-09-17 21:37:25 CST
  ✅ 上一轮正常结束（退出码 0）
  ✅ 状态文件存在（14482 字节），记录了 6 个监控源
  ✅ 推送凭据已配置
  ✅ 最近一轮：监控源 6 个，成功 6 个，告警 0 条，实际推送 0 条

结论：部署成功，且在正常工作。
```

**每一项为什么重要**：

| 检查项 | 不通过意味着 |
| --- | --- |
| 定时器已设开机自启 | 服务器一重启，监控就悄悄停了 |
| 定时器正在运行 + 有下一次触发时间 | 排班表没生效，永远不会自动跑 |
| 累计运行过 N 次 | 配了但一次都没真跑过（最常见） |
| 上一轮退出码 0 | 跑了但报错了，要去翻日志 |
| 状态文件存在 | 记录没落盘，重启后会重复推送旧内容 |
| 推送凭据已配置 | **最容易漏的一项**：程序在跑，但你收不到任何通知 |
| 最近一轮结论 | 抓取是否全部成功、有没有误报 |

**⚠️ 光看「定时器 active」不算成功。** `systemctl` 显示 active 只说明排班表在跑，
不代表每一轮都抓到了、也不代表能通知到你。必须同时满足「跑过 + 退出码 0 + 状态文件在长 + 凭据已配」。

想确认「它真的会按点自己跑」，最硬的证据是看历次运行时刻：

```bash
ssh root@192.168.0.10 "journalctl -u airshow-monitor.service --no-pager | grep 'Starting airshow'"
```

如果能看到 21:00、21:10、21:20、21:30 这样**每 10 分钟一条**的记录，就是真的在自动跑
（手动 `systemctl start` 也会产生记录，所以要看**时间点是否规律**，而不是只看条数）。

### 10.6 日常查看

```bash
# 定时器下次什么时候跑
ssh root@192.168.0.10 "systemctl list-timers airshow-monitor.timer"

# 最近一次运行日志
ssh root@192.168.0.10 "journalctl -u airshow-monitor.service -n 30 --no-pager"

# 只看报错
ssh root@192.168.0.10 "journalctl -u airshow-monitor.service -p err --no-pager | tail -20"
```

### 10.7 和 GitHub Actions 能同时开吗？

**可以，但不建议。** 两边各有一份 `state/`，互不知情，同一则开售公告可能给你推两次。
选一个就行：服务器稳，GitHub 免费且不用维护机器。

如果两边都开着又不想重复推送，可以把其中一边的 `config.json` 里
`notify.require_push_channel` 保持 `true`、但把推送通道换成一个不常用的（比如只留 Server酱），
这样重复推送至少不会都堆在微信上。
