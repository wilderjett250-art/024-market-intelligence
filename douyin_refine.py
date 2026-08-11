"""Turn one noisy Douyin speech transcript into a complete readable manuscript.

The refiner also extracts a compact news brief, but the complete manuscript is
the primary artifact.  It is intentionally source-bound: it may repair obvious
ASR wording, but it must not add facts that are absent from the transcript or
public chapter text.  The caller caches the result per video and version.
"""
from __future__ import print_function

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen


API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
REFINER_VERSION = os.environ.get("DOUYIN_AI_REFINER_VERSION", "douyin-news-v2")
USER_AGENT = "MarketIntelligenceDouyinRefiner/1.0"
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


def clean_manuscript(value):
    """Keep paragraph breaks while removing unsafe markup and empty spacing."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = []
    for block in re.split(r"\n\s*\n|(?<=[。！？])\s*\n", value):
        block = re.sub(r"[ \t]+", " ", block).strip()
        if block:
            paragraphs.append(block)
    return "\n\n".join(paragraphs)


def extract_json(content):
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I | re.S).strip()
    if not content:
        raise ValueError("AI returned empty content")
    return json.loads(content)


def normalize_result(result, source_transcript):
    raw_items = result.get("news_items") or result.get("items") or result.get("events") or []
    if not isinstance(raw_items, list):
        raw_items = []
    items = []
    for raw in raw_items[:12]:
        if not isinstance(raw, dict):
            continue
        headline = clean_text(raw.get("headline") or raw.get("title"), 60)
        summary = clean_text(raw.get("summary") or raw.get("fact"), 240)
        if not headline or len(summary) < 12:
            continue
        confidence = clean_text(raw.get("confidence"), 4)
        if confidence not in CONFIDENCE_VALUES:
            confidence = "中"
        entities = raw.get("entities") if isinstance(raw.get("entities"), list) else []
        entities = [clean_text(item, 30) for item in entities if clean_text(item, 30)][:6]
        items.append({
            "headline": headline,
            "summary": summary,
            "category": clean_text(raw.get("category"), 16) or "综合",
            "entities": entities,
            "market_relevance": clean_text(raw.get("market_relevance"), 160),
            "confidence": confidence,
            "uncertainty": clean_text(raw.get("uncertainty"), 120),
        })
    if not items:
        raise ValueError("AI returned no usable news items")
    overview = clean_text(result.get("overview"), 280)
    if not overview:
        overview = "本期视频共提炼出 %d 条可读新闻事件。" % len(items)
    manuscript = clean_manuscript(
        result.get("full_transcript")
        or result.get("complete_transcript")
        or result.get("manuscript")
    )
    source_chars = len(re.sub(r"\s+", "", source_transcript or ""))
    manuscript_chars = len(re.sub(r"\s+", "", manuscript))
    minimum_chars = max(160, int(source_chars * 0.5))
    if manuscript_chars < minimum_chars:
        raise ValueError(
            "full_transcript is incomplete: %d chars, expected at least %d"
            % (manuscript_chars, minimum_chars)
        )
    return overview, items, manuscript


def call_deepseek(source):
    if not API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    transcript = clean_text(source.get("transcript"), 50000)
    public_excerpt = clean_text(source.get("public_excerpt"), 12000)
    if len(transcript) < 40 and len(public_excerpt) < 40:
        raise ValueError("source transcript is too short")
    evidence = {
        "video_title": clean_text(source.get("title"), 300),
        "published_at": clean_text(source.get("published_at"), 50),
        "transcript_type": clean_text(source.get("transcript_type"), 40),
        "public_chapter_text": public_excerpt,
        "speech_to_text": transcript,
    }
    prompt = (
        "你是严谨的中文新闻文字编辑。任务有两个同等重要的输出：第一，按原视频顺序整理完整文字稿；第二，提炼新闻要点。"
        "只能使用下方提供的视频标题、公开章节文字和语音转写，不得补充外部知识，不得把推测写成事实。"
        "公开章节文字优先用于校正实体名称；只有上下文高度明确时才修复同音错字。"
        "full_transcript 必须是完整稿，不是摘要：保留原视频从开头到结尾出现的全部实质信息、先后顺序、日期、数字、主体、动作、因果、条件、限制与风险提示。"
        "可删除纯口头禅、明显重复和无意义转场，可补标点并分段，但不得删掉某一条新闻、不得合并掉细节、不得改写成短摘要。"
        "听不清且无法从公开章节文字校正的局部写成[听写不清]，不要猜词，也不要因为听不清就删掉整句。每个独立新闻事件单独成段。"
        "news_items 按独立事件拆分为 1 至 12 条，只做便于浏览的提炼，不替代 full_transcript。"
        "专名、数字、地点无法确定时在 uncertainty 中说明，不要猜测。"
        "每条 summary 必须回答已知范围内的谁、做了什么、在哪里或针对什么；market_relevance 只写与能源、航运、地缘或市场的直接关系，"
        "没有明确关系时返回空字符串。confidence 只能是高、中、低。禁止提供交易建议。"
        "返回 JSON 对象，结构严格为："
        '{"full_transcript":"按原视频顺序整理的完整中文文字稿，使用空行分段","overview":"本期核心概览","news_items":[{"headline":"中文标题","summary":"有效事实摘要",'
        '"category":"军事/外交/航运/能源/市场/科技/综合","entities":["实体"],'
        '"market_relevance":"直接影响或空字符串","confidence":"高/中/低","uncertainty":"不确定点或空字符串"}]}。\n\n'
        "输入证据：\n" + json.dumps(evidence, ensure_ascii=False)
    )
    last_error = None
    max_completion_tokens = min(8000, max(3200, int(len(transcript) * 1.8)))
    for attempt in range(2):
        payload = json.dumps({
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_completion_tokens,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        request = Request(API_URL, data=payload, headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = extract_json(content)
            overview, items, manuscript = normalize_result(result, transcript)
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return {
                "status": "ok",
                "ai_refiner_version": REFINER_VERSION,
                "ai_refiner_model": MODEL,
                "ai_refined_at": utc_now(),
                "ai_overview": overview,
                "ai_news_items": items,
                "ai_full_transcript": manuscript,
                "ai_usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except HTTPError as exc:
            last_error = exc
            if attempt == 0 and exc.code in {429, 500, 502, 503, 504}:
                time.sleep(2)
                continue
            raise
        except (ValueError, KeyError, TypeError) as exc:
            last_error = exc
            if attempt == 0:
                prompt += (
                    "\n\n上一次响应未通过校验：%s。请只返回完整、有效的 JSON 对象；"
                    "尤其不能把 full_transcript 写成摘要，必须覆盖从开头到结尾的全部实质内容。"
                    % clean_text(str(exc), 180)
                )
                continue
            raise
    raise RuntimeError(str(last_error or "AI refinement failed"))


def main():
    source = json.load(sys.stdin)
    result = call_deepseek(source)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
