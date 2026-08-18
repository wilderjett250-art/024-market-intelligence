# 024 市场情报终端 / Market Intelligence Terminal

> 把公开新闻和视频内容整理成带来源、带时间窗口、可回看的市场研判页面。
>
> **English:** Turns public news and video content into source-linked, time-bounded, replayable market intelligence pages.

## 解决什么问题 / Problem

公开信息分散，视频内容难整理，固定问题难以持续追踪；本项目把采集、视频理解、来源核验和定时摘要串成一个本地可复现的工作台。

**English:** Public information is fragmented, video content is difficult to organize, and recurring questions are hard to track. This project connects collection, video understanding, source checks, and scheduled summaries in a reproducible local workspace.

## 项目展示 / Demo

~~~mermaid
flowchart LR
 A[公开新闻 / RSS] --> C[来源核验]
 B[抖音公开视频] --> D[音画联合理解]
 C --> E[24 小时证据窗口]
 D --> E
 E --> F[固定问题研判页面]
 F --> G[历史视频回看]
~~~

页面每 15 秒刷新摘要，服务器同步任务每 2 分钟轮询一次公开视频；历史记录以 JSON 归档，可按视频查看概览、新闻要点和来源信息。

**English:** The page refreshes every 15 seconds while the server polls public videos every two minutes. Archived JSON records can be replayed with their overview, news points, and source information.

## 高光亮点 / Highlights

- **24 小时证据窗口**：固定回答美联储预期、期货与产业股票、中东与科技股三个方向。
  **English:** A strict 24-hour evidence window for rate expectations, futures and sector stocks, and Middle East/technology-stock changes.
- **原生视频理解**：使用 Doubao-Seed-2.0-lite 对公开视频进行音画联合理解，输出结构化新闻要点，避免把网页导航或评论误当成正文。
  **English:** Native audio-visual understanding with Doubao-Seed-2.0-lite produces structured news points without treating page chrome or comments as transcripts.
- **历史视频归档**：当前摘要和已处理视频按视频 ID 保存，支持列表与详情回看。
  **English:** Current and processed videos are archived by video ID for list and detail replay.
- **双模型故障转移**：定时研判优先使用 DeepSeek；遇到余额、限额、鉴权、接口或 JSON 输出异常时，自动切换豆包 Responses API，保留本轮研判结果。
  **English:** Scheduled analysis uses DeepSeek first and automatically fails over to the Doubao Responses API when quota, authentication, endpoint, or JSON output errors occur.
- **证据覆盖标注**：公开 RSS、行情快照和视频资料按主题建立证据目录；每条结论保留原文 URL，并标注多方来源、单源线索或暂无来源。
  **English:** RSS items, market snapshots, and video evidence are indexed by topic; every conclusion keeps its source URL and evidence-strength label.
- **来源与不确定性**：每个结论绑定输入 URL；单一来源或未经独立确认的报道标记为 `[未证实]`。
  **English:** Claims remain tied to supplied URLs, while single-source or unconfirmed reports are marked `[未证实]`.

## 技术名词 / Tech

`Python · HTML/CSS/JavaScript · Node.js · RSS · DeepSeek API · Volcengine Ark Responses API · FFmpeg · systemd`

## 从源码开始复现 / Reproduce from source

1. 克隆仓库并复制 `.env.example` 为 `.env`，只在本地填写自己的 API Key 和路径配置。
2. 安装 Python 依赖后运行 `python app.py`，默认监听 `http://127.0.0.1:19083`。
3. 打开首页，使用 `/health` 检查服务状态。
4. 先用少量公开来源验证，再按部署说明启用视频同步和定时任务。

```powershell
python app.py
```

运行定向测试，确认 DeepSeek 主模型、豆包回退和 Responses API JSON 解析：

```powershell
python -m unittest discover -s tests -v
```

**Expected result:** The local dashboard loads, the health endpoint responds, and configured public-source summaries appear without exposing credentials.

## 范围与安全 / Scope and Safety

只处理用户指定的公开来源。API Key、平台登录态、抓取缓存和服务器环境文件只存在于运行环境，不提交到仓库；生产部署请使用独立权限目录和最小网络权限。

**English:** Process only user-specified public sources. Keep API keys, platform sessions, crawl caches, and server environment files outside the repository, using least-privilege paths and network rules in production.

## 交流 / Contact

欢迎交流技术。

Open to technical exchange.

[English full version](README.en.md)
