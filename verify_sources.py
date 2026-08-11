"""Read-only, isolated multi-source verification for the market intelligence feed.

The production cache and AI digest are treated as an immutable snapshot.  This
tool writes only to a caller-selected verification directory and never updates
the files consumed by the dashboard.
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_TOPICS = ["中东互相打击", "霍尔木兹通航", "美军中东兵力"]
TOPIC_KEYWORDS = {
    "中东互相打击": (
        "strike", "attack", "missile", "drone", "rocket", "retaliat", "hezbollah", "houthi",
        "iran", "israel", "gaza", "lebanon", "red sea", "middle east", "袭击", "空袭", "导弹",
        "无人机", "报复", "真主党", "胡塞", "伊朗", "以色列", "加沙", "黎巴嫩", "红海",
    ),
    "霍尔木兹通航": (
        "hormuz", "strait", "tanker", "shipping", "vessel", "maritime", "航运", "油轮", "船舶", "通航", "霍尔木兹",
    ),
    "美军中东兵力": (
        "us military", "american troops", "troop", "deployment", "carrier", "base", "centcom", "pentagon",
        "美军", "兵力", "增兵", "撤军", "部署", "航母", "基地", "中央司令部",
    ),
}
OPPOSING_PAIRS = (
    (("increase", "增兵", "增加", "扩大", "部署"), ("decrease", "撤军", "减少", "撤出", "withdraw")),
    (("open", "reopen", "开放", "恢复"), ("close", "closed", "关闭", "中断")),
    (("attack", "strike", "袭击", "打击"), ("ceasefire", "truce", "停火", "和谈")),
)
USER_AGENT = "market-intelligence-verifier/1.0"


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return re.sub(r"\s+", " ", str(value)).strip()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def hostname(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def event_record(event):
    title = clean(event.get("title_original") or event.get("title"))
    summary = clean(event.get("summary"))
    url = clean(event.get("url"))
    return {
        "id": clean(event.get("id")),
        "title": title[:320],
        "summary": summary[:360],
        "source": clean(event.get("source")),
        "source_id": clean(event.get("source_id")),
        "published_at": clean(event.get("published_at")),
        "observed_at": clean(event.get("observed_at")),
        "url": url,
        "domain": hostname(url),
    }


def parse_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None


def has_keyword(text, keywords):
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def conflict_flag(records):
    text = " ".join((item["title"] + " " + item["summary"]) for item in records).lower()
    for left, right in OPPOSING_PAIRS:
        if has_keyword(text, left) and has_keyword(text, right):
            return True
    return False


def select_topic(topic, events, metrics, cutoff):
    keywords = TOPIC_KEYWORDS.get(topic, tuple(topic.split()))
    candidates = []
    for item in events:
        haystack = item["title"] + " " + item["summary"]
        if has_keyword(haystack, keywords):
            candidates.append(item)
    recent = [item for item in candidates if (parse_time(item["published_at"]) or parse_time(item["observed_at"]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    # A source may have a delayed timestamp.  Use the full frozen snapshot when
    # the 24-hour window contains no evidence, but keep the fallback explicit.
    selected = recent or candidates
    selected = sorted(selected, key=lambda item: (item["published_at"], item["observed_at"]), reverse=True)[:8]
    domains = sorted({item["domain"] for item in selected if item["domain"]})
    status = "未找到证据"
    if domains:
        status = "已确认" if len(domains) >= 2 else "单源线索"
        if conflict_flag(selected):
            status = "存在冲突"
    return {
        "topic": topic,
        "status": status,
        "window": "近24小时；无近24小时记录时回退至快照内相关记录",
        "independent_domains": domains,
        "evidence_count": len(selected),
        "evidence": selected,
        "metrics": [item for item in metrics if has_keyword(clean(item.get("name")) + " " + clean(item.get("commodity")), keywords)],
    }


def snapshot(data_dir, topics):
    cache = load_json(Path(data_dir) / "cache.json", {})
    ai = load_json(Path(data_dir) / "ai_digest.json", {})
    douyin = load_json(Path(data_dir) / "douyin_live.json", {})
    events = [event_record(item) for item in (cache.get("events") or []) if isinstance(item, dict)]
    metrics = [item for item in (cache.get("metrics") or []) if isinstance(item, dict)]
    cutoff = now_utc() - timedelta(hours=24)
    return {
        "captured_at": iso(now_utc()),
        "data_dir": str(Path(data_dir).resolve()),
        "cache_updated_at": clean(cache.get("last_updated")),
        "formal_ai_updated_at": clean(ai.get("updated_at")),
        "registered_source_count": len(cache.get("source_statuses") or {}),
        "event_count": len(events),
        "metric_count": len(metrics),
        "topics": [select_topic(topic, events, metrics, cutoff) for topic in topics],
        "douyin": {
            "title": clean(douyin.get("title")),
            "published_at": clean(douyin.get("published_at")),
            "url": clean(douyin.get("url")),
            "status": clean(douyin.get("status")),
        },
    }


def read_env_file(path):
    values = {}
    if not path:
        return values
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def ai_prompt(snapshot_data, style):
    compact = []
    for item in snapshot_data["topics"]:
        compact.append({
            "topic": item["topic"],
            "status_from_sources": item["status"],
            "independent_domains": item["independent_domains"],
            "evidence": [{key: record.get(key, "") for key in ("title", "summary", "source", "published_at", "url", "domain")} for record in item["evidence"][:8]],
        })
    instruction = (
        "按证据逐条核验，不要补充外部事实。" if style == "strict" else
        "专门寻找来源冲突、时间错位和把转载误当独立来源的风险。"
    )
    return (
        "你是信息核验编辑。" + instruction +
        "对每个主题返回 JSON 数组，每项含 topic、verdict、summary、used_domains、risks。"
        "verdict 只能是 已确认、单源线索、存在冲突、未找到证据；summary 不超过80字；"
        "used_domains 只能填写提供的域名；没有证据就明确写未找到证据。\n" +
        json.dumps(compact, ensure_ascii=False)
    )


def call_ai(snapshot_data, style, api_key, api_url, model):
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": ai_prompt(snapshot_data, style)}],
        "temperature": 0,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    request = Request(api_url, data=payload, headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    })
    with urlopen(request, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = clean((data.get("choices") or [{}])[0].get("message", {}).get("content"))
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I | re.S).strip()
    parsed = json.loads(content) if content else {}
    return {
        "style": style,
        "model": model,
        "result": parsed,
        "usage": data.get("usage") or {},
    }


def self_test():
    base = {"title": "", "summary": "", "source": "", "source_id": "", "published_at": "", "observed_at": "", "url": "", "domain": ""}
    one = dict(base, title="US military deployment near Hormuz", url="https://reuters.com/a", domain="reuters.com")
    two = dict(base, title="US troops deployed near Hormuz", url="https://apnews.com/b", domain="apnews.com")
    none = select_topic("美军中东兵力", [], [], now_utc() - timedelta(hours=24))
    single = select_topic("美军中东兵力", [one], [], now_utc() - timedelta(hours=24))
    confirmed = select_topic("美军中东兵力", [one, two], [], now_utc() - timedelta(hours=24))
    assert none["status"] == "未找到证据"
    assert single["status"] == "单源线索"
    assert confirmed["status"] == "已确认"
    print("self-test: ok")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run an isolated, read-only source verification snapshot")
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", str(Path(__file__).resolve().parent / "data")))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--call-ai", action="store_true", help="explicitly call DeepSeek; otherwise source-only")
    parser.add_argument("--env-file", default="", help="server-side env file; the key is never printed")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.runs < 1 or args.runs > 3:
        parser.error("--runs must be between 1 and 3")
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    # Keep generated reports beside the read-only data snapshot, never inside
    # the application release directory (which may be a symlink target).
    output_dir = Path(args.output_dir) if args.output_dir else Path(args.data_dir) / "verification" / stamp
    output_dir.mkdir(parents=True, exist_ok=False)
    frozen = snapshot(args.data_dir, args.topics)
    (output_dir / "snapshot.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "run_id": stamp,
        "mode": "isolated_read_only",
        "production_files_modified": [],
        "snapshot": "snapshot.json",
        "registered_source_count": frozen["registered_source_count"],
        "event_count": frozen["event_count"],
        "topics": [{key: item[key] for key in ("topic", "status", "evidence_count", "independent_domains")} for item in frozen["topics"]],
        "ai_runs": [],
    }
    if args.call_ai:
        env = read_env_file(args.env_file)
        api_key = os.environ.get("DEEPSEEK_API_KEY", "") or env.get("DEEPSEEK_API_KEY", "")
        api_url = os.environ.get("DEEPSEEK_API_URL", "") or env.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
        model = os.environ.get("DEEPSEEK_MODEL", "") or env.get("DEEPSEEK_MODEL", "deepseek-chat")
        if not api_key:
            raise RuntimeError("--call-ai requires DEEPSEEK_API_KEY or --env-file")
        for style in (["strict", "audit"] if args.runs > 1 else ["strict"]):
            try:
                result = call_ai(frozen, style, api_key, api_url, model)
            except Exception as exc:
                result = {"style": style, "model": model, "error": str(exc)[:200], "usage": {}}
            report["ai_runs"].append(result)
    (output_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "run_id": stamp,
        "output_dir": str(output_dir.resolve()),
        "registered_source_count": report["registered_source_count"],
        "event_count": report["event_count"],
        "topics": report["topics"],
        "ai_runs": len(report["ai_runs"]),
        "total_tokens": sum((item.get("usage") or {}).get("total_tokens", 0) for item in report["ai_runs"]),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
