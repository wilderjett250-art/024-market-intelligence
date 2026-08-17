"""Analyze one Douyin video with Volcengine Ark native video understanding.

The model receives the MP4 directly and returns only structured news items.
No speech transcript or full manuscript is generated or persisted.
"""
from __future__ import print_function

import base64
import html
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen


API_KEY = os.environ.get("ARK_API_KEY", "").strip()
API_URL = os.environ.get("ARK_RESPONSES_API_URL", "https://ark.cn-beijing.volces.com/api/v3/responses").strip()
MODEL = os.environ.get("ARK_VIDEO_MODEL", "doubao-seed-2-0-lite-260428").strip()
REFINER_VERSION = os.environ.get("DOUYIN_AI_REFINER_VERSION", "douyin-native-video-v1")
MAX_VIDEO_BYTES = int(os.environ.get("DOUYIN_AI_MAX_VIDEO_BYTES", str(45 * 1024 * 1024)))
USER_AGENT = "MarketIntelligenceDouyinVideoAnalyzer/2.0"
CONFIDENCE_VALUES = {"高", "中", "低"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value, limit=0):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] if limit else value


def extract_json(content):
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I | re.S).strip()
    if not content:
        raise ValueError("AI returned empty content")
    try:
        return json.loads(content)
    except ValueError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start:end + 1])
        raise


def response_text(data):
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks = []
    for item in data.get("output", []) if isinstance(data.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str) and text.strip():
                chunks.append(text)
    return "\n".join(chunks)


def normalize_result(result):
    raw_items = result.get("news_items") or result.get("items") or result.get("events") or []
    if not isinstance(raw_items, list):
        raw_items = []
    items = []
    for raw in raw_items[:16]:
        if not isinstance(raw, dict):
            continue
        headline = clean_text(raw.get("headline") or raw.get("title"), 72)
        summary = clean_text(raw.get("summary") or raw.get("fact"), 320)
        if not headline or len(summary) < 12:
            continue
        confidence = clean_text(raw.get("confidence"), 4)
        if confidence not in CONFIDENCE_VALUES:
            confidence = "中"
        entities = raw.get("entities") if isinstance(raw.get("entities"), list) else []
        entities = [clean_text(item, 30) for item in entities if clean_text(item, 30)][:8]
        items.append({
            "headline": headline,
            "summary": summary,
            "category": clean_text(raw.get("category"), 16) or "综合",
            "entities": entities,
            "market_relevance": clean_text(raw.get("market_relevance"), 180),
            "confidence": confidence,
            "uncertainty": clean_text(raw.get("uncertainty"), 160),
        })
    if not items:
        raise ValueError("AI returned no usable news items")
    overview = clean_text(result.get("overview"), 320)
    if not overview:
        overview = "本期视频共提炼出 %d 条有效新闻信息。" % len(items)
    return overview, items


def video_data_url(video_path):
    if not video_path or not os.path.isfile(video_path):
        raise ValueError("video_path is missing")
    size = os.path.getsize(video_path)
    if size < 100000:
        raise ValueError("video file is too small")
    if size > MAX_VIDEO_BYTES:
        raise ValueError("video exceeds configured upload limit: %d bytes" % size)
    mime_type = mimetypes.guess_type(video_path)[0] or "video/mp4"
    with open(video_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return "data:%s;base64,%s" % (mime_type, encoded), size


def call_ark(source):
    if not API_KEY:
        raise RuntimeError("ARK_API_KEY is not configured")
    media_url, video_bytes = video_data_url(source.get("video_path"))
    context = {
        "video_title": clean_text(source.get("title"), 300),
        "published_at": clean_text(source.get("published_at"), 50),
        "public_chapter_text": clean_text(source.get("public_excerpt"), 12000),
    }
    prompt = (
        "你是中文新闻编辑，请直接理解所附视频的画面、声音、字幕和时间顺序，将视频中的有效新闻整理为结构化 JSON。"
        "不要生成逐字稿、全文转写或视频介绍；不要把抖音页面按钮、评论、推荐列表、账号统计、广告和栏目标签当作新闻。"
        "新闻按视频出现顺序拆分为 1 至 16 条，每个独立事件一条；不得因为篇幅而漏掉后半段。"
        "每条 summary 在视频可确认范围内交代谁、做了什么、地点或对象、时间与关键数字。"
        "只能根据视频本身和随附的公开章节文字判断，不使用外部知识补全。专名、数字、地点、时间、主体或因果不清楚时，"
        "应省略不确定表述或写入 uncertainty，不能猜测。market_relevance 只写对能源、航运、地缘或市场的直接影响，"
        "没有直接关系时返回空字符串。confidence 只能是高、中、低。禁止提供交易建议。"
        "严格只返回一个 JSON 对象，结构为："
        '{"overview":"本期核心概览","news_items":[{"headline":"中文新闻标题","summary":"有效事实摘要",'
        '"category":"军事/外交/航运/能源/市场/科技/综合","entities":["实体"],'
        '"market_relevance":"直接影响或空字符串","confidence":"高/中/低","uncertainty":"不确定点或空字符串"}]}。\n\n'
        "作品辅助信息：" + json.dumps(context, ensure_ascii=False)
    )
    last_error = None
    for attempt in range(2):
        payload = json.dumps({
            "model": MODEL,
            "input": [{
                "role": "user",
                "content": [
                    {"type": "input_video", "video_url": media_url},
                    {"type": "input_text", "text": prompt},
                ],
            }],
            "thinking": {"type": "disabled"},
            "max_output_tokens": 6000,
        }).encode("utf-8")
        request = Request(API_URL, data=payload, headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urlopen(request, timeout=210) as response:
                data = json.loads(response.read().decode("utf-8"))
            result = extract_json(response_text(data))
            overview, items = normalize_result(result)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return {
                "status": "ok",
                "ai_refiner_version": REFINER_VERSION,
                "ai_source_mode": "native_video",
                "ai_refiner_model": MODEL,
                "ai_refined_at": utc_now(),
                "ai_overview": overview,
                "ai_news_items": items,
                "ai_full_transcript": "",
                "ai_video_bytes": video_bytes,
                "ai_usage": {
                    "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)),
                    "output_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            last_error = RuntimeError("Ark HTTP %d: %s" % (exc.code, clean_text(body, 420)))
            if attempt == 0 and exc.code in {408, 409, 429, 500, 502, 503, 504}:
                time.sleep(2)
                continue
            raise last_error
        except (ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if attempt == 0:
                prompt += "\n\n上一次响应未通过校验：%s。请补全遗漏事件，并且只返回有效 JSON。" % clean_text(str(exc), 180)
                continue
            raise
    raise RuntimeError(str(last_error or "Ark video analysis failed"))


def main():
    source = json.load(sys.stdin)
    result = call_ark(source)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
