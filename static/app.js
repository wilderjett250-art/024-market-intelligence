(() => {
  const state = { data: null, query: "", history: [], historyLoaded: false, selectedHistoryId: "" };
  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value = "") => String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
  const watch = [
    ["影响美联储加息减息预期的消息", "近24小时内影响美联储加息减息预期的消息"],
    ["期货与产业股票利多利空", "近24小时内银、锡、碳酸锂、原油期货，商业航天、内存、人形机器人、核电股票有哪些明显的利空利多消息"],
    ["中东兵力、通航与美国科技股", "近24小时美军在中东的增减兵力动态，美国伊朗动态，霍尔木兹通航量变化，美国科技股价的变化"],
  ];

  function toDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hour12: false, timeZone: "Asia/Taipei",
    }).format(date).replace(/\//g, "-");
  }
  function timeAgo(value) {
    if (!value) return "等待数据";
    const timestamp = new Date(value).getTime();
    if (Number.isNaN(timestamp)) return "等待数据";
    const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
    return minutes < 1 ? "刚刚" : minutes < 60 ? `${minutes} 分钟前` : minutes < 1440 ? `${Math.floor(minutes / 60)} 小时前` : `${Math.floor(minutes / 1440)} 天前`;
  }
  function match(item) {
    const query = state.query.trim().toLowerCase();
    return !query || [item.title, item.summary, item.source, item.change].join(" ").toLowerCase().includes(query);
  }
  function sourceLabel(url) {
    try {
      const host = new URL(url).hostname.replace(/^www\./, "");
      return host.split(".")[0].replace(/[-_]+/g, " ");
    } catch (_) {
      return "公开来源";
    }
  }
  function douyinLines(value) {
    const noise = /^(开启读屏标签|读屏标签已关闭|精选|推荐|AI抖音|关注|朋友|我的|直播|放映厅|短剧|小游戏|全球局势速报|搜索|充钻石|客户端|通知|消息|投稿|登录|登录后可发布弹幕|发送|倍速|智能|清屏|连播|举报|全部评论|请先登录后发表评论|大家都在搜|分享|回复|展开\d+条回复|立即登录|播放中|推荐视频|作者|粉丝|获赞|\.{2,}|\d{1,2}:\d{2}\s*\/\s*\d{1,2}:\d{2}|\d+[\.\d]*万?$)/;
    return String(value || "").split(/\r?\n+/).map((line) => line.trim()).filter((line) => line && !noise.test(line) && !/^\d+$/.test(line));
  }
  function douyinSummary(record, aiSummary = "") {
    if (record.ai_source_mode === "native_video") return { summary: record.ai_overview || "豆包已完成原生视频理解。", full: "" };
    const raw = String(record.transcript || record.excerpt || "");
    const lines = douyinLines(raw);
    const hasDigest = /章节要点/.test(raw);
    if (record.transcript_type === "local_vosk_asr" && lines.length) {
      return { summary: `已完成本地语音转写，共 ${lines.length} 段`, full: lines.join("\n") };
    }
    const useful = hasDigest ? lines.filter((line) => line !== "章节要点") : [];
    if (useful.length) return { summary: `已提取 ${useful.length} 段公开章节文字`, full: useful.join("\n") };
    if (aiSummary) return { summary: aiSummary, full: "" };
    return { summary: "本期作品已同步，页面暂未公开可直接提取的逐条文字稿。点击原作品查看完整视频。", full: "" };
  }
  function douyinNewsDigest(record) {
    const items = Array.isArray(record.ai_news_items) ? record.ai_news_items : [];
    if (!items.length) return "";
    const cards = items.map((item, index) => {
      const entities = (item.entities || []).slice(0, 5).map((entity) => `<span>${escapeHtml(entity)}</span>`).join("");
      const relevance = item.market_relevance ? `<p class="news-relevance"><b>关注影响</b>${escapeHtml(item.market_relevance)}</p>` : "";
      const uncertainty = item.uncertainty ? `<p class="news-uncertainty">待核对：${escapeHtml(item.uncertainty)}</p>` : "";
      return `<article class="douyin-news-item"><div class="news-index">${String(index + 1).padStart(2, "0")}</div><div><div class="news-meta"><span>${escapeHtml(item.category || "综合")}</span><i>可信度 ${escapeHtml(item.confidence || "中")}</i></div><h4>${escapeHtml(item.headline || "新闻事件")}</h4><p class="news-summary">${escapeHtml(item.summary || "")}</p>${relevance}${uncertainty}${entities ? `<div class="news-entities">${entities}</div>` : ""}</div></article>`;
    }).join("");
    return `<section class="douyin-ai-digest"><div class="digest-title"><div><span>本期速览</span><strong>${items.length} 条有效信息</strong></div><small>按视频顺序整理</small></div><p class="digest-overview">${escapeHtml(record.ai_overview || "已按独立事件完成整理。")}</p><div class="douyin-news-grid">${cards}</div></section>`;
  }
  function topicCard(topic) {
    const urls = topic.sources || [];
    const sourceLinks = urls.slice(0, 3).map((url, index) => `<a class="tag geo" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">证据 ${index + 1} · ${escapeHtml(sourceLabel(url))} ↗</a>`).join("");
    const details = (topic.details || []).map((item) => {
      const links = (item.sources || []).slice(0, 2).map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(sourceLabel(url))} ↗</a>`).join("");
      return `<li><div><b>${escapeHtml(item.label || "重点变化")}</b><i>${escapeHtml(item.change || "待确认")}</i></div><p>${escapeHtml(item.summary || "")}</p>${links ? `<small>${links}</small>` : ""}</li>`;
    }).join("");
    return `<article class="event-row ai-row"><div class="event-time"><b>AI</b><small>定时问询</small></div><div class="event-body"><div class="event-kicker"><span>多源信息综合</span><i>${escapeHtml(topic.change || "待确认")}</i><em class="status-pill">08:30 / 20:30</em></div><h3>${escapeHtml(topic.title)}</h3><p class="ai-question">${escapeHtml(topic.question || "近 24 小时有哪些明显变化？")}</p><p class="ai-conclusion">${escapeHtml(topic.summary || "本轮多源证据中暂无可核实的明确变化。")}</p>${details ? `<ul class="ai-detail-list">${details}</ul>` : ""}<div class="event-tags">${sourceLinks || '<span class="tag">公开证据不足，等待下一轮</span>'}</div></div></article>`;
  }
  function douyinCard(record, aiSummary = "", options = {}) {
    const url = record.url || "";
    const { summary, full } = douyinSummary(record, aiSummary);
    const refined = Array.isArray(record.ai_news_items) && record.ai_news_items.length;
    const newsDigest = douyinNewsDigest(record);
    const syncText = record.status === "error" ? `同步异常 · ${timeAgo(record.checked_at)}` : record.status === "stale" ? `最近可验证作品 · ${timeAgo(record.checked_at)}` : `最近同步 · ${timeAgo(record.checked_at)}`;
    const nativeVideo = record.ai_source_mode === "native_video";
    const modeText = nativeVideo ? `豆包视频提炼 · ${timeAgo(record.ai_refined_at || record.checked_at)}` : refined ? `AI 新闻提炼 · ${timeAgo(record.ai_refined_at || record.checked_at)}` : aiSummary && !full ? "AI 归纳 · 基于公开信源" : syncText;
    const rawText = String(record.transcript || record.excerpt || "");
    const publicText = String(record.public_excerpt || "");
    const polishedText = String(record.ai_full_transcript || "").trim();
    const manuscript = nativeVideo ? "" : polishedText || full || rawText;
    const manuscriptChars = manuscript.replace(/\s/g, "").length;
    const asrConfidence = Number(record.transcript_confidence);
    const lowConfidence = record.transcript_type === "local_vosk_asr" && Number.isFinite(asrConfidence) && asrConfidence < 0.78;
    const publicChapterMode = record.ai_source_mode === "public_chapters";
    const manuscriptLabel = lowConfidence ? "语音转写核查稿" : polishedText ? "完整视频文字稿" : record.transcript_type === "local_vosk_asr" ? "机器听写全文" : "公开视频文字";
    const manuscriptNote = lowConfidence ? `机器识别清晰度 ${Math.round(asrConfidence * 100)}%，新闻摘要仅采用公开视频章节` : polishedText ? "AI 校订自完整语音转写，按原视频顺序整理" : "按已采集到的公开内容完整展示";
    const manuscriptPanel = manuscript ? `<details class="full-manuscript"><summary><div><span>${escapeHtml(manuscriptLabel)}</span><strong>${escapeHtml(manuscriptNote)}</strong></div><small>${manuscriptChars} 字<i>展开查看</i></small></summary><div class="manuscript-text">${escapeHtml(manuscript)}</div></details>` : "";
    const publicPanel = publicText && publicText !== rawText ? `<section><b>公开视频章节文字</b><p>${escapeHtml(publicText)}</p></section>` : "";
    const auditPanel = !nativeVideo && polishedText && rawText ? `<details class="excerpt-details"><summary>查看校订前原始听写</summary>${publicPanel}<section><b>本地语音识别原文</b><p>${escapeHtml(rawText)}</p></section></details>` : "";
    const channelLabel = options.history ? "回放" : "实时";
    const channelNote = options.history ? "历史记录" : "抖音同步";
    return `<article class="event-row excerpt-row${options.history ? " history-replay" : ""}"><div class="event-time"><b>${channelLabel}</b><small>${channelNote}</small></div><div class="event-body"><div class="event-kicker"><span>全球速探（抖音）</span><i>${escapeHtml(modeText)}</i></div><h3>${escapeHtml(record.title || "本期作品概览")}</h3>${refined ? newsDigest : `<p class="excerpt-summary">${escapeHtml(summary)}</p>`}${manuscriptPanel}${auditPanel}<div class="event-tags"><span class="tag">发布 ${escapeHtml(record.published_at ? toDate(record.published_at) : "公开作品")}</span>${refined ? `<span class="tag ai-summary-tag">${nativeVideo ? "豆包原生视频理解" : publicChapterMode ? "章节文字提炼" : "AI 新闻提炼"}</span>` : aiSummary && !full ? '<span class="tag ai-summary-tag">AI 归纳</span>' : ""}${url ? `<a class="tag geo" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开原作品 ↗</a>` : ""}</div></div></article>`;
  }
  function eventCard(event) {
    const tags = [...(event.commodities || []), ...(event.factors || [])].slice(0, 5).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
    return `<article class="event-row ${event.urgency === "高" ? "urgent" : ""}"><div class="event-time"><b>${toDate(event.published_at)}</b><small>发现 ${toDate(event.observed_at)}</small></div><div class="event-body"><div class="event-kicker"><span>${escapeHtml(event.source)}</span><i>${escapeHtml(event.tier)}</i></div><h3>${escapeHtml(event.title)}</h3>${event.summary ? `<p>${escapeHtml(event.summary)}</p>` : ""}<div class="event-tags">${tags}<a class="tag geo" href="${escapeHtml(event.url)}" target="_blank" rel="noreferrer">原始链接 ↗</a></div></div></article>`;
  }
  function renderEvents() {
    const data = state.data;
    if (!data) return;
    const digest = data.ai_digest;
    const digestCards = (digest?.topics || []).filter(match).map(topicCard);
    const fallback = digest && digest.source_excerpt ? {
      status: "stale",
      source: "全球速探（抖音）",
      url: digest.source_url,
      title: digest.source_title,
      excerpt: digest.source_excerpt,
      ai_overview: digest.source_overview,
      ai_news_items: digest.source_news_items,
      ai_full_transcript: digest.source_full_transcript,
      published_at: digest.source_published_at,
      checked_at: digest.updated_at || digest.evidence_updated_at,
    } : null;
    const liveRecord = data.douyin_live;
    const liveUsable = liveRecord && (liveRecord.status === "ok" || liveRecord.transcript || (liveRecord.ai_news_items || []).length);
    const douyin = liveUsable ? liveRecord : (fallback || liveRecord);
    const refinedSearch = (douyin?.ai_news_items || []).map((item) => `${item.headline || ""} ${item.summary || ""}`).join(" ");
    const excerpt = douyin && match({ title: douyin.title, summary: `${douyin.excerpt || ""} ${douyin.ai_full_transcript || ""} ${douyin.ai_overview || ""} ${refinedSearch}`, source: douyin.source, change: "" }) ? [douyinCard(douyin, digest?.douyin_summary || "")] : [];
    const liveItems = excerpt;
    $("#live-list").innerHTML = liveItems.join("") || '<div class="terminal-empty">当前没有匹配的实时快讯。</div>';
    $("#ai-list").innerHTML = digestCards.join("") || '<div class="terminal-empty">本轮 AI 研判等待下一次定时整理。</div>';
  }
  function renderWatch() {
    const topics = state.data?.ai_digest?.topics || [];
    $("#watch-list").innerHTML = watch.map(([title, detail]) => {
      const topic = topics.find((item) => item.title === title);
      return `<div><span class="watch-rule" aria-hidden="true"></span><p><b>${escapeHtml(title)}</b><small>${escapeHtml(detail)}</small></p><em class="watch-state">${escapeHtml(topic?.change || "等待整理")}</em></div>`;
    }).join("");
  }
  function historySeries(title = "") {
    const match = String(title).match(/第\s*(\d+)\s*集/);
    return match ? `第 ${match[1]} 集` : "历史作品";
  }
  function historyDate(value) {
    if (!value) return "时间待核对";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hour12: false, timeZone: "Asia/Taipei",
    }).format(date).replace(/\//g, "-");
  }
  function renderHistoryList() {
    const list = state.history;
    $("#history-count").textContent = `${list.length} 条记录`;
    $("#history-list").innerHTML = list.map((record) => {
      const active = record.video_id === state.selectedHistoryId;
      const stateText = record.news_count ? `${record.news_count} 条要点` : record.has_transcript ? "保留文字资料" : "仅保留索引";
      return `<button class="history-entry${active ? " active" : ""}" type="button" data-video-id="${escapeHtml(record.video_id)}"><time>${escapeHtml(historyDate(record.published_at))}</time><strong>${escapeHtml(historySeries(record.title))}</strong><span>${escapeHtml(record.title)}</span><small>${escapeHtml(stateText)}<i>查看回放 →</i></small></button>`;
    }).join("") || '<div class="terminal-empty small">当前还没有可回放的历史记录；下一条新作品同步后会自动归档。</div>';
  }
  async function openHistory(videoId) {
    if (!videoId) return;
    state.selectedHistoryId = videoId;
    renderHistoryList();
    $("#history-detail").innerHTML = '<div class="terminal-empty"><span class="pulse"></span> 正在读取回放…</div>';
    try {
      const response = await fetch(`/api/history/${encodeURIComponent(videoId)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(response.status);
      const record = await response.json();
      $("#history-detail").innerHTML = douyinCard(record, "", { history: true });
    } catch (_) {
      $("#history-detail").innerHTML = '<div class="terminal-empty error">这条历史记录暂时无法读取，请稍后重试。</div>';
    }
  }
  async function loadHistory(force = false) {
    if (state.historyLoaded && !force) return;
    try {
      const response = await fetch("/api/history", { cache: "no-store" });
      if (!response.ok) throw new Error(response.status);
      const payload = await response.json();
      state.history = Array.isArray(payload.records) ? payload.records : [];
      state.historyLoaded = true;
      if (state.selectedHistoryId && !state.history.some((record) => record.video_id === state.selectedHistoryId)) state.selectedHistoryId = "";
      renderHistoryList();
      if (state.history.length && !state.selectedHistoryId) openHistory(state.history[0].video_id);
    } catch (_) {
      $("#history-list").innerHTML = '<div class="terminal-empty small error">无法读取历史记录，请稍后重试。</div>';
      $("#history-count").textContent = "读取失败";
    }
  }
  function renderSignals() {
    const data = state.data;
    const digest = data.ai_digest;
    const live = data.douyin_live;
    const topics = data.ai_digest?.topics || [];
    const hasDouyin = Boolean(data.douyin_live?.title || digest?.source_title);
    $("#event-count").textContent = hasDouyin ? "1" : "0";
    $("#healthy-count").textContent = topics.length;
    $("#digest-status").textContent = digest?.source_status === "ok" ? "已更新" : digest?.source_status === "empty" ? "待证据" : "待确认";
    $("#digest-detail").textContent = live?.checked_at ? `抖音作品 ${timeAgo(live.checked_at)}同步` : (digest?.note || "多源主信息流，每日两次综合");
    $("#last-updated").textContent = data.last_updated ? `${toDate(data.last_updated)} · ${timeAgo(data.last_updated)}` : "等待首次整理";
    $("#refresh-note").textContent = data.refresh_in_progress ? "正在更新抖音作品" : `抖音 ${live?.status === "ok" ? "独立同步" : "等待有效作品"} · AI 每日两次问询`;
  }
  function render() { renderSignals(); renderEvents(); renderWatch(); }
  async function loadDashboard({ quiet = false } = {}) {
    const button = $("#reload");
    if (!quiet) button.classList.add("spinning");
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store" });
      if (!response.ok) throw new Error(response.status);
      state.data = await response.json();
      render();
      if (state.historyLoaded) loadHistory(true);
    } catch (_) {
      if (!state.data) $("#live-list").innerHTML = '<div class="terminal-empty error">无法读取信息服务，请稍后刷新。</div>';
    } finally {
      if (!quiet) button.classList.remove("spinning");
    }
  }
  function clock() {
    $("#clock").textContent = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date());
  }
  let scrollTimer = null;
  window.addEventListener("scroll", () => {
    document.body.classList.add("is-scrolling");
    window.clearTimeout(scrollTimer);
    scrollTimer = window.setTimeout(() => document.body.classList.remove("is-scrolling"), 650);
  }, { passive: true });
  $("#search").addEventListener("input", (event) => { state.query = event.target.value; renderEvents(); });
  document.querySelectorAll(".section-tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".section-tab").forEach((item) => item.classList.toggle("active", item === tab));
    document.querySelectorAll(".section-panel").forEach((panel) => panel.classList.toggle("mobile-active", panel.id === tab.dataset.section));
    const historyMode = tab.dataset.section === "history-panel";
    document.body.classList.toggle("history-mode", historyMode);
    if (historyMode) loadHistory();
  }));
  $("#history-list").addEventListener("click", (event) => {
    const entry = event.target.closest("[data-video-id]");
    if (entry) openHistory(entry.dataset.videoId);
  });
  $("#reload").addEventListener("click", () => loadDashboard());
  clock();
  setInterval(clock, 1000);
  loadDashboard();
  setInterval(() => loadDashboard({ quiet: true }), 15000);
})();
