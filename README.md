# 全球速探｜公开作品摘录台

一个用于人工研判的私有信息终端。前端分为「全球速探」和「AI 研判」两栏：前者同步指定抖音账号的完整视频文字，后者按固定问题整理近 24 小时公开信息。

## 第一版范围

- 实时栏目：只显示抖音账号「全球速探」的最新公开作品；
- 视频整理：新作品先在服务器完成本地语音转写，再由 DeepSeek 输出按原视频顺序保留的完整校订稿和独立新闻要点；同一视频按版本缓存，不重复调用；
- 定时 AI：每日 08:30、20:30（Asia/Taipei）综合后台公开信息，回答三组近 24 小时问题；
- 问题一：影响美联储加息、减息预期的消息；
- 问题二：银、锡、碳酸锂、原油期货及商业航天、内存、人形机器人、核电股票的明显利多利空；
- 问题三：美军中东增减兵、中东互相打击、霍尔木兹通航量及美国科技股价格变化；
- 必答结构：三组问题固定展开为 16 个子项，每项都单独回答；没有可靠证据时明确显示“未提及”，不会省略；
- 后台证据：IRNA、Al Jazeera English、OilPrice.com、The Jerusalem Post、Federal Reserve、CNBC Markets、MarketWatch、SpaceNews、Tom's Hardware、Nuclear Newswire、Electrek 等公开源；前端不单独展示来源状态栏，只在结论下保留实际使用的原文链接；
- 行情快照：每轮读取白银、锡、碳酸锂、原油、英伟达和特斯拉的公开行情，价格涨跌与新闻利多利空分开表述；
- 页面每 15 秒读取一次最新摘要状态；
- 超出 24 小时的旧消息不会进入定时 AI 证据包；没有有效证据时显示“待确认”，不使用旧消息填空；
- 抖音文字稿保留原作品入口和校订前的机器听写，便于人工核对。

免费公开来源的发布和缓存速度决定了最终时效。商业快讯、AIS 货物流、Reuters、Bloomberg、Platts 与 Argus 将在第二版通过正式订阅接口接入。

## 本地运行

## 多源核验

`verify_sources.py` 是与正式信息流隔离的只读核验工具。它从指定数据目录建立一次冻结快照，按主题整理来源域名、发布时间和原文链接，并把结果写入 `data/verification/<run_id>/`；不会覆盖 `cache.json`、`ai_digest.json`、`douyin_live.json`，也不会改变网页接口。

只做来源核验：

```powershell
python .\verify_sources.py --data-dir .\data
```

显式开启 AI 测试时，工具会在同一快照上运行一次严格核验和一次冲突审计，最多保留两轮短输出，并记录接口返回的 `usage` token：

```powershell
python .\verify_sources.py --data-dir .\data --call-ai --runs 2 --env-file .\.env
```

服务器上建议把报告写入 `/var/lib/market-intelligence/verification/`，该目录不通过网页公开。来源状态只表示当前快照的证据强度：至少两个不同域名为“已确认”，一个域名为“单源线索”，检测到相反表述为“存在冲突”，没有匹配证据为“未找到证据”。同一新闻的转载不会被重复计为独立来源。

要求：Python 3.6+，不需要安装第三方包。

```powershell
Set-Location E:\wordspace\6.26\market-intelligence-terminal
$env:HOST = '127.0.0.1'
$env:PORT = '19083'
python .\app.py
```

打开 `http://127.0.0.1:19083`，健康检查为 `http://127.0.0.1:19083/health`。

`EIA_API_KEY` 可选。未提供时使用 EIA 的演示密钥；生产环境建议申请个人免费密钥，以获得独立额度。

## 服务器发布边界

京东云目标采用独立资源：

- 应用：`market-intelligence.service`；
- 抖音同步：`market-intelligence-douyin.service` + `market-intelligence-douyin.timer`，每 10 分钟读取一次公开作品；
- 监听：`0.0.0.0:19083`；
- 程序：`/opt/market-intelligence/current`；
- 持久缓存：`/var/lib/market-intelligence`；
- 子域名入口：单独的反向代理虚拟主机或 Cloudflare Named Tunnel ingress。

公开仓库不记录实际服务器地址。部署时可通过独立域名或反向代理子路径访问，例如 `https://your-domain.example/market-intel/`；应用使用独立服务和专用端口，不占用现有网站的 80 端口。

`deploy/market-intelligence.service`、`deploy/nginx.market-intelligence.conf.template` 和 `deploy/cloudflared.ingress.yml.template` 都是隔离配置。它们不修改现有 80 端口应用、`knowledge-cosmos.service` 或现有 Quick Tunnel。

全球速探（抖音）使用独立的浏览器采集运行时，结果写入 `douyin_live.json`，网页信息流每 15 秒读取一次最新状态。采集失败时保留最近一次通过质量校验的作品，不把受限提示写入信息流。

语音转写由服务器本地 Vosk 小模型完成；DeepSeek 只接收视频标题、公开章节文字和转写文本，输出完整校订稿与结构化新闻要点。页面直接展示完整校订稿，并将原始语音转写收纳在核对区。`market-intelligence-douyin.service` 通过服务器环境文件读取 API 凭证，仓库和前端不包含密钥。

在绑定子域名前，先确认根域名和 DNS 控制方式；发布后必须验证：本地 `/health`、反向代理域名 `/health`、证书、页面首轮采集以及现有 80 端口站点仍可访问。
