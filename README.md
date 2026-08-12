# 024 市场情报终端 / Market Intelligence Terminal

> 定时采集公开新闻、视频文字和语音，按固定问题整理证据并生成带来源链接的市场研判页面。
>
> **English:** Collects public news, video text, and speech on a schedule, then generates source-linked market intelligence pages for fixed questions.

## 解决什么问题 / Problem

公开信息分散、来源难核验，视频内容难整理，固定问题也难以持续追踪。

**English:** Public information is fragmented and hard to verify, video content is difficult to organize, and recurring questions are hard to track.

## 项目展示 / Demo

~~~mermaid
flowchart LR
 A[RSS / 公开新闻] --> C[来源核验]
 B[视频文字 / 语音] --> C
 C --> D[24 小时证据窗口]
 D --> E[固定问题摘要页面]
~~~

采集、转写、来源核验和摘要生成各自可追溯，不把模型摘要当作无来源结论。

**English:** Collection, transcription, source checks, and summaries remain traceable instead of presenting model output as an unsourced conclusion.

## 高光亮点 / Highlights

- 公开新闻/RSS 多源采集。
  **English:** Multi-source public-news and RSS collection.
- 视频文字整理与本地 Vosk 转写。
  **English:** Video-text processing and local Vosk transcription.
- 24 小时证据窗口和来源链接。
  **English:** A 24-hour evidence window with source links.
- DeepSeek 定时摘要与行情快照。
  **English:** Scheduled DeepSeek summaries and market snapshots.

## 技术名词 / Tech

`Python · HTML/CSS/JavaScript · RSS · Vosk · DeepSeek API`

## 从 ZIP 开始复现 / Reproduce from ZIP

1. 解压 ZIP，复制 `.env.example` 为 `.env`，填写自己的 API Key。
2. 执行 `python app.py`，默认监听 `http://127.0.0.1:19083`。
3. 打开首页查看最新摘要，健康检查地址为 `/health`。
4. 先用少量公开来源验证，再配置定时任务和完整采集范围。

**Expected result:** 完成上述步骤后，应能看到项目的页面、窗口、设备输出或测试结果。

**Expected result:** After these steps, you should see the project's page, window, device output, or test result.

## 范围与安全 / Scope and Safety

只采集公开来源；API Key、调度配置和抓取结果属于本地运行数据，不要提交或公开传播。

**English:** Collect public sources only; API keys, schedules, and fetched results are local runtime data and must not be committed or publicly shared.

## 交流 / Contact

欢迎交流技术。

Open to technical exchange.

[English full version](README.en.md)
