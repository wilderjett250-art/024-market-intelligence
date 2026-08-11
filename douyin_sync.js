#!/usr/bin/env node
/*
 * Browser-backed synchronizer for the public "全球速探" Douyin account.
 * Douyin serves a JavaScript challenge to plain HTTP clients, so this job
 * intentionally uses one short-lived headless Chromium session and publishes
 * only data visible on the public profile/video pages.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { chromium } = require("playwright");

const PROFILE_URL = process.env.DOUYIN_PROFILE_URL || "https://www.douyin.com/user/MS4wLjABAAAAtrR3ZhxoEcDIwEpnBqfbNdf2R9f9w4QiSXCaRU431uuiL73K5qaBXTda0njLcQnv";
const SEED_VIDEO_URL = process.env.DOUYIN_SEED_VIDEO_URL || "https://www.douyin.com/video/7666492917388791081";
const DATA_DIR = path.resolve(process.env.DATA_DIR || path.join(__dirname, "data"));
const OUTPUT_PATH = path.resolve(process.env.DOUYIN_LIVE_PATH || path.join(DATA_DIR, "douyin_live.json"));
const BROWSER_PATH = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined;
const USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36";
const ASR_ENABLED = process.env.DOUYIN_ASR_ENABLED === "1";
const ASR_SCRIPT = process.env.DOUYIN_ASR_SCRIPT || path.join(__dirname, "douyin_asr.py");
const ASR_MODEL = process.env.DOUYIN_ASR_MODEL || "/opt/market-intelligence/tools/vosk-model-small-cn-0.22";
const ASR_PYTHON = process.env.DOUYIN_ASR_PYTHON || "/usr/libexec/platform-python";
const ASR_FFMPEG = process.env.DOUYIN_ASR_FFMPEG || "/opt/market-intelligence/tools/ffmpeg";
const ASR_MEDIA_DIR = path.resolve(process.env.DOUYIN_ASR_MEDIA_DIR || path.join(DATA_DIR, "douyin_media"));
const AI_REFINE_ENABLED = process.env.DOUYIN_AI_REFINE_ENABLED === "1";
const AI_REFINE_SCRIPT = process.env.DOUYIN_AI_REFINE_SCRIPT || path.join(__dirname, "douyin_refine.py");
const AI_REFINER_VERSION = process.env.DOUYIN_AI_REFINER_VERSION || "douyin-news-v2";

function nowIso() { return new Date().toISOString(); }
function readExisting() {
  try { return JSON.parse(fs.readFileSync(OUTPUT_PATH, "utf8")); } catch (_) { return {}; }
}
function writeJson(value) {
  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  const tempPath = `${OUTPUT_PATH}.tmp-${process.pid}`;
  fs.writeFileSync(tempPath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(tempPath, OUTPUT_PATH);
}
function cleanText(value) {
  return String(value || "").replace(/\u00a0/g, " ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}
function normalizeUrl(url) {
  try { return new URL(url, "https://www.douyin.com").toString().split("?")[0]; } catch (_) { return url; }
}
function seriesLink(item) {
  return item && /全球局势速看/.test(item.text || "") && /\/video\/\d+/.test(item.href || "");
}
function pickLatest(items) {
  const candidates = items.filter(seriesLink);
  if (!candidates.length) return null;
  return candidates.sort((a, b) => {
    const ai = Number((a.href.match(/\/video\/(\d+)/) || [])[1] || 0);
    const bi = Number((b.href.match(/\/video\/(\d+)/) || [])[1] || 0);
    return bi - ai;
  })[0];
}
function titleFromBody(body, pageTitle, linkText) {
  const lines = body.split("\n").map(cleanText).filter(Boolean);
  const match = lines.find((line) => /^第\s*\d+\s*集/.test(line) && /全球局势速看/.test(line));
  if (match) return match;
  const title = cleanText(pageTitle).replace(/\s+-\s*抖音\s*$/, "");
  if (title) return title;
  return cleanText(linkText).replace(/^\d[\d\.万]*\s+/, "");
}
function publishedFromBody(body) {
  const match = body.match(/发布时间：\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
  if (!match) return "";
  return `${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:00+08:00`;
}
function excerptFromBody(body, title) {
  const start = body.indexOf("章节要点");
  if (start < 0) return cleanText(body.slice(0, 1200));
  const endMarkers = ["发布时间：", title].filter(Boolean).map((marker) => body.indexOf(marker, start + 4)).filter((index) => index > start);
  const end = endMarkers.length ? Math.min(...endMarkers) : Math.min(body.length, start + 9000);
  // Keep the complete public chapter panel.  The previous 9,000-character
  // cap could silently turn a long work into a partial transcript.
  return cleanText(body.slice(start, end)).slice(0, 30000);
}
async function downloadVideoToTemp(video, videoId, mediaSource) {
  const source = mediaSource || await video.locator("video").evaluate((node) => node.currentSrc || node.src || "");
  if (!source || source.startsWith("blob:")) throw new Error("视频原始媒体地址未出现在公开网络响应中");
  const response = await fetch(source, {
    headers: {
      "User-Agent": USER_AGENT,
      Referer: "https://www.douyin.com/",
      Origin: "https://www.douyin.com",
      Accept: "*/*",
    },
  });
  if (!response.ok) throw new Error(`媒体请求失败：${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length < 100000) throw new Error(`媒体响应过小：${bytes.length} bytes`);
  fs.mkdirSync(ASR_MEDIA_DIR, { recursive: true });
  const temp = path.join(ASR_MEDIA_DIR, `${videoId || "latest"}.mp4.tmp`);
  const final = path.join(ASR_MEDIA_DIR, `${videoId || "latest"}.mp4`);
  fs.writeFileSync(temp, bytes);
  fs.renameSync(temp, final);
  return final;
}
function runLocalAsr(videoPath) {
  const wavPath = `${videoPath}.wav`;
  try {
    const convert = spawnSync(ASR_FFMPEG, ["-hide_banner", "-loglevel", "error", "-y", "-i", videoPath, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wavPath], {
      encoding: "utf8", timeout: 150000, maxBuffer: 1024 * 1024,
    });
    if (convert.error || convert.status !== 0) throw new Error(`音频转换失败：${String(convert.stderr || convert.error || "unknown").slice(0, 180)}`);
    const result = spawnSync(ASR_PYTHON, [ASR_SCRIPT, "--audio", wavPath, "--model", ASR_MODEL], {
      encoding: "utf8", timeout: 150000, maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: process.env.PYTHONPATH || "/opt/market-intelligence/tools/vosk-python" },
    });
    if (result.error || result.status !== 0) throw new Error(`本地语音识别失败：${String(result.stderr || result.error || "unknown").slice(0, 180)}`);
    const line = String(result.stdout || "").trim().split(/\r?\n/).pop();
    const parsed = JSON.parse(line || "{}");
    if (parsed.status !== "ok" || !parsed.text) throw new Error("本地语音识别没有返回文字");
    return parsed;
  } finally {
    try { fs.unlinkSync(wavPath); } catch (_) {}
    try { fs.unlinkSync(videoPath); } catch (_) {}
  }
}
function runAiRefiner(record) {
  const result = spawnSync(ASR_PYTHON, [AI_REFINE_SCRIPT], {
    input: JSON.stringify({
      video_id: record.video_id,
      title: record.title,
      published_at: record.published_at,
      transcript_type: record.transcript_type,
      transcript: record.transcript,
      public_excerpt: record.public_excerpt,
    }),
    encoding: "utf8", timeout: 90000, maxBuffer: 4 * 1024 * 1024,
    env: process.env,
  });
  if (result.error || result.status !== 0) throw new Error(`AI 新闻提炼失败：${String(result.stderr || result.error || "unknown").slice(0, 300)}`);
  const line = String(result.stdout || "").trim().split(/\r?\n/).pop();
  const parsed = JSON.parse(line || "{}");
  if (parsed.status !== "ok" || !parsed.ai_full_transcript || !Array.isArray(parsed.ai_news_items) || !parsed.ai_news_items.length) throw new Error("AI 没有返回完整文字稿和有效新闻条目");
  return parsed;
}
function copyFields(target, source, fields) {
  for (const field of fields) {
    if (source[field] !== undefined) target[field] = source[field];
  }
}
async function extractLinks(page, selector) {
  return page.locator(selector).evaluateAll((nodes) => nodes.map((node) => ({ href: node.href, text: (node.innerText || node.textContent || "").trim() })));
}
async function sync() {
  const checkedAt = nowIso();
  const browser = await chromium.launch({ headless: true, executablePath: BROWSER_PATH, args: ["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"] });
  try {
    const context = await browser.newContext({ userAgent: USER_AGENT, locale: "zh-CN", timezoneId: "Asia/Shanghai", viewport: { width: 1440, height: 1100 } });
    await context.addInitScript(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => undefined });
      Object.defineProperty(navigator, "languages", { get: () => ["zh-CN", "zh", "en-US", "en"] });
      Object.defineProperty(navigator, "plugins", { get: () => [1, 2, 3] });
    });
    const profile = await context.newPage();
    await profile.goto(`${PROFILE_URL}?from_tab_name=main`, { waitUntil: "domcontentloaded", timeout: 60000 });
    await profile.waitForTimeout(20000);
    let links = await extractLinks(profile, 'ul[data-e2e="scroll-list"] a[href*="/video/"]');
    if (!links.length) links = await extractLinks(profile, 'a[href*="/video/"]');
    let profileLatest = pickLatest(links);
    if (!profileLatest) {
      const existing = readExisting();
      const seedUrl = existing.url && /\/video\/\d+/.test(existing.url) ? existing.url : SEED_VIDEO_URL;
      profileLatest = { href: seedUrl, text: "全球局势速看" };
    }

    // A video page exposes the account's adjacent latest works. Walk a few
    // adjacent pages because the profile list itself can be several releases
    // behind when Douyin serves it to an unauthenticated browser.
    const probe = await context.newPage();
    let latest = profileLatest;
    for (let hop = 0; hop < 3; hop += 1) {
      await probe.goto(normalizeUrl(latest.href), { waitUntil: "domcontentloaded", timeout: 60000 });
      await probe.waitForTimeout(13000);
      const relatedLinks = await extractLinks(probe, 'a[href*="/video/"]');
      const candidate = pickLatest([latest, ...relatedLinks]);
      const currentId = Number((latest.href.match(/\/video\/(\d+)/) || [])[1] || 0);
      const candidateId = Number((candidate && candidate.href.match(/\/video\/(\d+)/) || [])[1] || 0);
      if (!candidate || candidateId <= currentId) break;
      latest = candidate;
    }
    await probe.close();

    const video = await context.newPage();
    let mediaSource = "";
    let audioSource = "";
    video.on("response", (response) => {
      const contentType = String(response.headers()["content-type"] || "");
      if (!/^video\//.test(contentType)) return;
      if (/media-audio/.test(response.url())) audioSource = response.url();
      else if (/media-video/.test(response.url())) mediaSource = response.url();
    });
    await video.goto(normalizeUrl(latest.href), { waitUntil: "domcontentloaded", timeout: 60000 });
    await video.waitForTimeout(9000);
    const body = await video.locator("body").innerText();
    const pageTitle = await video.title();
    const title = titleFromBody(body, pageTitle, latest.text);
    const publishedAt = publishedFromBody(body);
    const excerpt = excerptFromBody(body, title);
    const record = {
      status: "ok",
      source: "全球速探（抖音）",
      profile_url: PROFILE_URL,
      url: normalizeUrl(latest.href),
      video_id: ((latest.href.match(/\/video\/(\d+)/) || [])[1] || ""),
      title,
      excerpt,
      transcript: excerpt,
      transcript_type: "douyin_public_chapters",
      published_at: publishedAt,
      checked_at: checkedAt,
      synced_at: checkedAt,
      method: "public browser page",
      quality_ok: true,
    };
    const targetTitle = /^第\s*\d+\s*集.*全球局势速看/.test(record.title || "");
    const unavailable = /视频不存在|作品不存在|页面不存在|视频数据加载中/.test(body);
    if (!record.video_id || !targetTitle || unavailable || !record.excerpt || !/发布时间：|第\s*\d+\s*集/.test(body)) throw new Error("作品页面未返回可验证的全球速探作品正文");
    const existing = readExisting();
    const sameVideo = existing.video_id === record.video_id;
    record.public_excerpt = excerpt;
    if (sameVideo && existing.transcript_type === "local_vosk_asr" && existing.transcript) {
      copyFields(record, existing, ["transcript", "transcript_type", "transcript_words", "transcript_model", "transcript_sample_rate"]);
    } else if (ASR_ENABLED) {
      try {
        const mediaPath = await downloadVideoToTemp(video, record.video_id, audioSource || mediaSource);
        const asr = runLocalAsr(mediaPath);
        record.transcript = asr.text;
        record.transcript_type = "local_vosk_asr";
        record.transcript_words = asr.words || [];
        record.transcript_model = asr.model || path.basename(ASR_MODEL);
        record.transcript_sample_rate = asr.sample_rate || 16000;
      } catch (asrError) {
        record.transcript = excerpt;
        record.transcript_type = "douyin_public_chapters";
        record.transcript_error = String(asrError && asrError.message || asrError).slice(0, 300);
      }
    } else {
      record.transcript = excerpt;
      record.transcript_type = "douyin_public_chapters";
    }
    record.excerpt = record.transcript || excerpt;
    const reusableRefinement = sameVideo
      && existing.ai_refiner_version === AI_REFINER_VERSION
      && existing.ai_full_transcript
      && Array.isArray(existing.ai_news_items)
      && existing.ai_news_items.length;
    if (reusableRefinement) {
      copyFields(record, existing, ["ai_refiner_version", "ai_refiner_model", "ai_refined_at", "ai_overview", "ai_news_items", "ai_full_transcript", "ai_usage"]);
    } else if (AI_REFINE_ENABLED && record.transcript) {
      try {
        Object.assign(record, runAiRefiner(record));
      } catch (refineError) {
        if (sameVideo && Array.isArray(existing.ai_news_items) && existing.ai_news_items.length) {
          copyFields(record, existing, ["ai_refiner_version", "ai_refiner_model", "ai_refined_at", "ai_overview", "ai_news_items", "ai_full_transcript", "ai_usage"]);
        }
        record.ai_refine_error = String(refineError && refineError.message || refineError).slice(0, 500);
      }
    }
    writeJson(record);
    console.log(JSON.stringify({ status: record.status, video_id: record.video_id, title: record.title, published_at: record.published_at, checked_at: record.checked_at }));
  } finally {
    await browser.close();
  }
}

sync().catch((error) => {
  const checkedAt = nowIso();
  const existing = readExisting();
  const existingIsUsable = existing.quality_ok && /^第\s*\d+\s*集.*全球局势速看/.test(existing.title || "") && !/视频不存在|作品不存在|页面不存在/.test(existing.excerpt || "");
  const failed = existingIsUsable ? { ...existing, status: "error", checked_at: checkedAt, last_error: String(error && error.message || error).slice(0, 300) } : { status: "error", source: "全球速探（抖音）", profile_url: PROFILE_URL, checked_at: checkedAt, last_error: String(error && error.message || error).slice(0, 300) };
  try { writeJson(failed); } catch (_) { /* systemd journal retains the error */ }
  console.error(JSON.stringify({ status: "error", checked_at: checkedAt, error: failed.last_error }));
  process.exitCode = 1;
});
