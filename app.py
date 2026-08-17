#!/usr/bin/env python3
"""Market intelligence terminal: a dependency-free collector and SPA server.

The server deliberately preserves source links, publication time, and first-seen
time. It does not generate summaries, sentiment, or trading recommendations.
"""
from __future__ import print_function

import hashlib
import json
import mimetypes
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlencode, urlparse, unquote, quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


APP_VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
CACHE_PATH = DATA_DIR / "cache.json"
AI_DIGEST_PATH = DATA_DIR / "ai_digest.json"
DOUYIN_LIVE_PATH = DATA_DIR / "douyin_live.json"
DOUYIN_HISTORY_DIR = DATA_DIR / "douyin_history"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "19083"))
REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "60"))
EIA_SECONDS = int(os.environ.get("EIA_SECONDS", "900"))
WORLDMONITOR_API_KEY = os.environ.get("WORLDMONITOR_API_KEY", "").strip()
USER_AGENT = "MarketIntelligenceTerminal/0.1 (+private research dashboard)"




RSS_SOURCES = [
    {
        "id": "irna",
        "name": "IRNA 伊朗通讯社",
        "url": "https://en.irna.ir/rss",
        "tier": "官方媒体",
        "kind": "伊朗官方表态",
        "coverage": "伊朗、制裁、石油出口、地区局势",
    },
    {
        "id": "aljazeera",
        "name": "Al Jazeera English",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "tier": "地区媒体",
        "kind": "中东动态",
        "coverage": "中东冲突、海事风险、地缘事件",
    },
    {
        "id": "oilprice",
        "name": "OilPrice.com",
        "url": "https://oilprice.com/rss/main",
        "tier": "行业媒体",
        "kind": "能源基本面",
        "coverage": "原油、OPEC、炼厂、库存与油运",
    },
    {
        "id": "jpost",
        "name": "The Jerusalem Post",
        "url": "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
        "tier": "地区媒体",
        "kind": "以色列动态",
        "coverage": "以色列政策、内塔尼亚胡、地区安全",
    },
    {
        "id": "bbc_mideast",
        "name": "BBC Middle East",
        "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
        "tier": "国际通讯媒体",
        "kind": "中东 RSS",
        "coverage": "中东冲突、海湾安全、伊朗与以色列动态",
    },
]

SCHEDULED_SOURCES = [
    {
        "id": "eia",
        "name": "EIA 美国能源信息署",
        "tier": "官方数据",
        "kind": "周度库存",
        "coverage": "美国商业原油库存、供应、需求代理指标",
        "url": "https://www.eia.gov/petroleum/data.php/summary",
        "state": "数据轮询",
    },
    {
        "id": "opec",
        "name": "OPEC",
        "tier": "官方机构",
        "kind": "月度供需",
        "coverage": "OPEC+ 政策、MOMR、全球油市平衡",
        "url": "https://publications.opec.org/momr/information/2476",
        "state": "发布日历",
    },
    {
        "id": "ukmto",
        "name": "UKMTO / JMIC",
        "tier": "运行机构",
        "kind": "海事安全",
        "coverage": "霍尔木兹、红海、油轮与航运安全通报",
        "url": "https://www.ukmto.org/",
        "state": "发布日历",
    },
    {
        "id": "spa",
        "name": "SPA 沙特通讯社",
        "tier": "官方媒体",
        "kind": "海湾官方表态",
        "coverage": "沙特政府与能源政策",
        "url": "https://www.spa.gov.sa/en",
        "state": "原站追踪",
    },
    {
        "id": "wam",
        "name": "WAM 阿联酋通讯社",
        "tier": "官方媒体",
        "kind": "海湾官方表态",
        "coverage": "阿联酋政府与地区能源动态",
        "url": "https://www.wam.ae/en",
        "state": "原站追踪",
    },
]

# Registered first-party and cross-check feeds. These entries are shown in the
# source board immediately; RSS/API adapters can be enabled independently.
REGISTERED_SOURCES = [
    {"id": "fars", "name": "法尔斯通讯社 Fars News Agency", "tier": "伊朗媒体", "kind": "IRGC 首发线索", "coverage": "伊朗革命卫队、袭击与报复公告", "url": "https://www.farsnews.ir/en", "state": "入口已登记"},
    {"id": "tasnim", "name": "塔斯尼姆通讯社 Tasnim News Agency", "tier": "伊朗媒体", "kind": "圣城旅与代理人武装", "coverage": "伊朗安全与代理人武装消息", "url": "https://www.tasnimnews.com/en", "state": "入口已登记"},
    {"id": "reuters", "name": "路透 Reuters", "tier": "全球通讯社", "kind": "突发与交叉核对", "coverage": "胡塞声明、特朗普、内塔尼亚胡、中东冲突", "url": "https://www.reuters.com/world/middle-east/", "state": "入口已登记"},
    {"id": "bloomberg", "name": "彭博 Bloomberg", "tier": "全球通讯社", "kind": "交易与能源", "coverage": "油价、库存、船运与美国能源政策", "url": "https://www.bloomberg.com/energy", "state": "入口已登记"},
    {"id": "ap", "name": "美联社 AP", "tier": "全球通讯社", "kind": "事实交叉核对", "coverage": "中东冲突与公开声明", "url": "https://apnews.com/hub/middle-east", "state": "入口已登记"},
    {"id": "houthi_statement", "name": "胡塞武装公开声明", "tier": "冲突原始信号", "kind": "声明交叉追踪", "coverage": "海上行动、红海与报复声明（以正规通讯社转载为准）", "url": "https://www.reuters.com/world/middle-east/", "state": "入口已登记"},
    {"id": "trump_statement", "name": "特朗普公开言论", "tier": "政治原始信号", "kind": "Truth Social", "coverage": "美国对伊朗、中东与能源政策表态", "url": "https://truthsocial.com/@realDonaldTrump", "state": "入口已登记"},
    {"id": "netanyahu_statement", "name": "内塔尼亚胡公开言论", "tier": "政治原始信号", "kind": "官方社交账号", "coverage": "以色列安全、伊朗与地区冲突表态", "url": "https://x.com/netanyahu", "state": "入口已登记"},
    {"id": "douyin_global_fast", "name": "全球速探（抖音）", "tier": "中文观察账号", "kind": "公开作品", "coverage": "只摘录账号作品中明确提到的四个专题", "url": "https://www.douyin.com/user/MS4wLjABAAAAtrR3ZhxoEcDIwEpnBqfbNdf2R9f9w4QiSXCaRU431uuiL73K5qaBXTda0njLcQnv", "state": "已接入 AI 摘录"},
    {"id": "jin10_hormuz", "name": "霍尔木兹每日通航量（金十数据）", "tier": "航运数据", "kind": "每日专题", "coverage": "霍尔木兹海峡船舶通行与航运风险", "url": "https://qihuo.jin10.com/topic/strait_of_hormuz.html", "state": "入口已登记"},
    {"id": "nvidia_quote", "name": "英伟达 NVIDIA", "tier": "市场数据", "kind": "公开行情入口", "coverage": "NVDA 股价与半导体需求线索", "url": "https://finance.yahoo.com/quote/NVDA/", "state": "入口已登记"},
    {"id": "tesla_quote", "name": "特斯拉 Tesla", "tier": "市场数据", "kind": "公开行情入口", "coverage": "TSLA 股价与电动车需求线索", "url": "https://finance.yahoo.com/quote/TSLA/", "state": "入口已登记"},
    {"id": "spacex_quote", "name": "SpaceX", "tier": "市场数据", "kind": "公司与估值入口", "coverage": "SpaceX 未上市，保留公司公告与融资估值线索", "url": "https://www.spacex.com/", "state": "未上市"},
    {"id": "fedwatch", "name": "CME 美联储观察 CME FedWatch", "tier": "利率预期", "kind": "期货隐含概率", "coverage": "联邦基金利率目标区间的市场隐含预期", "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html", "state": "入口已登记"},
    {"id": "federal_reserve", "name": "美联储 Federal Reserve", "tier": "官方机构", "kind": "FOMC 原始文件", "coverage": "利率决议、会议纪要、官员讲话与经济预测", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "state": "入口已登记"},
    {"id": "worldmonitor", "name": "World Monitor", "tier": "全球情报补充", "kind": "可选 API / MCP", "coverage": "冲突、军事态势、海运、能源与市场数据（配置凭证后启用）", "url": "https://www.worldmonitor.app/", "state": "需要 API Key"},
]

CORE_SOURCE_IDS = {
    "fars", "tasnim", "reuters", "bloomberg", "aljazeera", "houthi_statement",
    "trump_statement", "netanyahu_statement", "douyin_global_fast", "nvidia_quote",
    "tesla_quote", "spacex_quote", "jin10_hormuz", "fedwatch", "federal_reserve",
}

# The terminal remains a multi-source research feed.  The Douyin account is a
# distinct, tightly scoped module rather than a replacement for the main feed.
VISIBLE_SOURCE_IDS = set(item["id"] for item in RSS_SOURCES + SCHEDULED_SOURCES + REGISTERED_SOURCES)
ACTIVE_RSS_SOURCE_IDS = {"irna", "aljazeera", "oilprice", "jpost"}
ACTIVE_SCHEDULED_SOURCE_IDS = {"eia"}

COMMODITY_RULES = [
    ("原油", ("crude", "oil", "opec", "brent", "wti", "refinery", "barrel", "petroleum", "tanker", "gasoline", "diesel")),
    ("碳酸锂", ("lithium", "lithium carbonate", "ev battery", "battery material")),
    ("白银", ("silver", "bullion")),
    ("铜", ("copper", "copper mine", "smelter")),
    ("锡", ("tin", "solder")),
]

FACTOR_RULES = [
    ("库存", ("inventory", "inventories", "stockpile", "stocks", "warehouse", "storage", "spr")),
    ("供应", ("supply", "production", "output", "cut", "outage", "export", "sanction", "refinery", "mine")),
    ("需求", ("demand", "consumption", "imports", "manufacturing", "sales", "economic growth")),
    ("航运", ("hormuz", "strait", "tanker", "vessel", "shipping", "maritime", "red sea", "port")),
    ("地缘", ("iran", "israel", "houthi", "hezbollah", "guard", "trump", "netanyahu", "military", "missile", "attack", "war")),
]

STATE_LOCK = threading.RLock()
REFRESH_LOCK = threading.Lock()
TRANSLATION_CACHE = {}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def initial_state():
    return {
        "version": APP_VERSION,
        "last_updated": None,
        "refresh_in_progress": False,
        "events": [],
        "metrics": [],
        "source_statuses": {},
        "errors": [],
    }


def load_state():
    if not CACHE_PATH.exists():
        return initial_state()
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        state = initial_state()
        state.update(loaded)
        return state
    except (OSError, ValueError):
        return initial_state()


STATE = load_state()


def persist_state(snapshot):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_PATH.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(str(temporary), str(CACHE_PATH))


def strip_markup(value):
    if not value:
        return ""
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, wanted):
    wanted = wanted.lower()
    for child in list(element):
        if local_name(child.tag) == wanted:
            return " ".join(part.strip() for part in child.itertext() if part and part.strip())
    return ""


def child_link(element):
    for child in list(element):
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        if href:
            return href
        text = " ".join(part.strip() for part in child.itertext() if part and part.strip())
        if text:
            return text
    return ""


def iso_timestamp(raw, fallback):
    if not raw:
        return fallback
    candidate = raw.strip()
    try:
        parsed = parsedate_to_datetime(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, IndexError):
        pass
    try:
        normalized = candidate.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return fallback


def parse_utc_iso(value):
    """Parse the cache timestamp without relying on Python 3.7's fromisoformat."""
    if not value:
        raise ValueError("missing timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def classify(title, summary):
    corpus = (title + " " + summary).lower()
    commodities = [label for label, terms in COMMODITY_RULES if any(term_matches(corpus, term) for term in terms)]
    factors = [label for label, terms in FACTOR_RULES if any(term_matches(corpus, term) for term in terms)]
    if not commodities:
        commodities = ["全球市场"]
    if not factors:
        factors = ["待研判"]
    urgency_terms = ("attack", "missile", "war", "hormuz", "sanction", "outage", "emergency", "strike")
    urgency = "高" if any(term_matches(corpus, term) for term in urgency_terms) else "常规"
    return commodities, factors, urgency


def term_matches(corpus, term):
    """Match short English tokens as words so 'tin' does not match 'meeting'."""
    if len(term) <= 4 and " " not in term:
        return re.search(r"\b" + re.escape(term) + r"\b", corpus) is not None
    return term in corpus


def request_bytes(url, timeout=8):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, application/json, text/html"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def translate_title(text):
    """Translate English headlines to Chinese while preserving the source title."""
    value = (text or "").strip()
    if not value or not re.search(r"[A-Za-z]", value):
        return value
    cached = TRANSLATION_CACHE.get(value)
    if cached:
        return cached
    endpoints = [
        "https://api.mymemory.translated.net/get?q=" + quote(value[:420]) + "&langpair=en%7Czh-CN",
        "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + quote(value[:420]),
    ]
    for endpoint in endpoints:
        try:
            payload = json.loads(request_bytes(endpoint, timeout=5).decode("utf-8"))
            translated = payload.get("responseData", {}).get("translatedText", "") if isinstance(payload, dict) else ""
            if not translated and isinstance(payload, list) and payload and payload[0]:
                translated = "".join(part[0] for part in payload[0] if part and part[0])
            translated = translated.strip()
            if translated and "MYMEMORY WARNING" not in translated.upper():
                TRANSLATION_CACHE[value] = translated
                return translated
        except Exception:
            continue
    return value


def fetch_rss(source, known_events):
    body = request_bytes(source["url"])
    root = ET.fromstring(body)
    observed_at = utc_now()
    candidates = []
    for item in root.iter():
        tag = local_name(item.tag)
        if tag not in ("item", "entry"):
            continue
        title = strip_markup(child_text(item, "title"))
        link = child_link(item)
        if not title or not link:
            continue
        raw_summary = child_text(item, "description") or child_text(item, "summary") or child_text(item, "content")
        summary = strip_markup(raw_summary)[:420]
        published = iso_timestamp(child_text(item, "pubdate") or child_text(item, "published") or child_text(item, "updated"), observed_at)
        digest = hashlib.sha256((source["id"] + "|" + link).encode("utf-8")).hexdigest()[:20]
        commodities, factors, urgency = classify(title, summary)
        if commodities == ["全球市场"] and factors == ["待研判"]:
            continue
        candidates.append({
            "digest": digest,
            "title": title,
            "summary": summary,
            "url": link,
            "published": published,
            "commodities": commodities,
            "factors": factors,
            "urgency": urgency,
        })

    # Translation is an enrichment step.  Run it in a small pool so one
    # overseas translation endpoint cannot hold the entire RSS refresh open for
    # many minutes.  A failed translation falls back to the original title.
    translated = {}
    if candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            futures = {pool.submit(translate_title, item["title"]): item["digest"] for item in candidates}
            for future in as_completed(futures):
                digest = futures[future]
                try:
                    translated[digest] = future.result()
                except Exception:
                    translated[digest] = ""

    events = []
    for item in candidates:
        digest = item["digest"]
        prior = known_events.get(digest, {})
        events.append({
            "id": digest,
            "title": (translated.get(digest) or item["title"])[:420],
            "title_original": item["title"][:420],
            "summary": item["summary"],
            "url": item["url"],
            "source_id": source["id"],
            "source": source["name"],
            "tier": source["tier"],
            "source_kind": source["kind"],
            "published_at": item["published"],
            "observed_at": prior.get("observed_at", observed_at),
            "commodities": item["commodities"],
            "factors": item["factors"],
            "urgency": item["urgency"],
        })
    return events[:80]


def collect_rss_source(source, known_events, working):
    """Collect one RSS source without letting its failure abort other feeds."""
    status = base_source_status(source, working)
    status["last_attempt"] = utc_now()
    try:
        events = fetch_rss(source, known_events)
        status["state"] = "正常"
        status["last_success"] = utc_now()
        status["article_count"] = len(events)
        status["error"] = ""
        return source["id"], status, events, None
    except Exception as exc:
        status["state"] = "延迟"
        status["error"] = str(exc)[:180]
        return source["id"], status, [], {"source": source["name"], "message": status["error"], "at": utc_now()}


def eia_metric():
    api_key = os.environ.get("EIA_API_KEY", "DEMO_KEY")
    params = [
        ("api_key", api_key),
        ("frequency", "weekly"),
        ("data[0]", "value"),
        ("facets[product][]", "EPC0"),
        ("facets[duoarea][]", "NUS"),
        ("facets[process][]", "SAX"),
        ("length", "2"),
        ("sort[0][column]", "period"),
        ("sort[0][direction]", "desc"),
    ]
    endpoint = "https://api.eia.gov/v2/petroleum/stoc/wstk/data/?" + urlencode(params)
    payload = json.loads(request_bytes(endpoint).decode("utf-8"))
    records = payload.get("response", {}).get("data", [])
    if not records:
        raise RuntimeError("EIA returned no commercial crude inventory records")
    latest = records[0]
    prior = records[1] if len(records) > 1 else None
    latest_value = float(latest["value"])
    prior_value = float(prior["value"]) if prior and prior.get("value") is not None else None
    return {
        "id": "eia_us_crude_inventory",
        "name": "美国商业原油库存",
        "commodity": "原油",
        "value": latest_value,
        "unit": "千桶",
        "delta": latest_value - prior_value if prior_value is not None else None,
        "period": latest.get("period"),
        "source": "EIA 美国能源信息署",
        "source_url": "https://www.eia.gov/petroleum/data.php/summary",
        "updated_at": utc_now(),
    }


def base_source_status(source, state):
    previous = state.get("source_statuses", {}).get(source["id"], {})
    current = {
        "id": source["id"],
        "name": source["name"],
        "tier": source["tier"],
        "kind": source["kind"],
        "coverage": source["coverage"],
        "url": source["url"],
        "core": source.get("core", source["id"] in CORE_SOURCE_IDS),
        "state": source.get("state", "等待首轮采集") if source["id"] in VISIBLE_SOURCE_IDS else previous.get("state", source.get("state", "等待首轮采集")),
        "last_attempt": previous.get("last_attempt"),
        "last_success": previous.get("last_success"),
        "article_count": previous.get("article_count", 0),
        "error": previous.get("error", ""),
    }
    return current


def refresh_all():
    if not REFRESH_LOCK.acquire(False):
        return
    try:
        with STATE_LOCK:
            working = json.loads(json.dumps(STATE, ensure_ascii=False))
            working["refresh_in_progress"] = True
        known_events = {
            event["id"]: event
            for event in working.get("events", [])
            if event.get("id") and event.get("source_id") in VISIBLE_SOURCE_IDS and not (
                event.get("commodities") == ["全球市场"] and event.get("factors") == ["待研判"]
            )
        }
        translation_budget = 3
        for event in known_events.values():
            original = event.get("title_original") or event.get("title", "")
            if translation_budget and re.search(r"[A-Za-z]", original):
                translated = translate_title(original)
                event["title_original"] = original
                event["title"] = translated[:420]
                translation_budget -= 1
        source_statuses = {}
        harvested = []
        errors = []

        active_sources = [source for source in RSS_SOURCES if source["id"] in ACTIVE_RSS_SOURCE_IDS]
        # Fetch feeds concurrently.  A blocked overseas endpoint is isolated to
        # its own 8-second request timeout and cannot hold the other sources or
        # the next refresh cycle hostage.
        with ThreadPoolExecutor(max_workers=min(4, len(active_sources) or 1)) as pool:
            futures = {
                pool.submit(collect_rss_source, source, known_events, working): source
                for source in active_sources
            }
            for future in as_completed(futures):
                source_id, status, new_events, error = future.result()
                source_statuses[source_id] = status
                harvested.extend(new_events)
                if error:
                    errors.append(error)

        for source in SCHEDULED_SOURCES:
            if source["id"] not in ACTIVE_SCHEDULED_SOURCE_IDS:
                continue
            status = base_source_status(source, working)
            source_statuses[source["id"]] = status

        for source in REGISTERED_SOURCES:
            if source["id"] not in VISIBLE_SOURCE_IDS:
                continue
            status = base_source_status(source, working)
            source_statuses[source["id"]] = status

        eia_status = source_statuses.get("eia")
        previous_eia_attempt = eia_status.get("last_attempt") if eia_status else None
        # A prior run may have recorded the attempt but not persisted the
        # metric (for example after a restart).  Treat an empty metric list as
        # due immediately so the dashboard does not stay at "waiting" forever.
        due_for_eia = not working.get("metrics")
        if previous_eia_attempt and working.get("metrics"):
            try:
                previous_time = parse_utc_iso(previous_eia_attempt)
                due_for_eia = (datetime.now(timezone.utc) - previous_time).total_seconds() >= EIA_SECONDS
            except ValueError:
                due_for_eia = True
        if eia_status and due_for_eia:
            eia_status["last_attempt"] = utc_now()
            try:
                metric = eia_metric()
                working["metrics"] = [metric]
                eia_status["state"] = "正常"
                eia_status["last_success"] = utc_now()
                eia_status["error"] = ""
            except Exception as exc:
                eia_status["state"] = "延迟"
                eia_status["error"] = str(exc)[:180]
                errors.append({"source": "EIA 美国能源信息署", "message": eia_status["error"], "at": utc_now()})

        merged = dict(known_events)
        for event in harvested:
            merged[event["id"]] = event
        events = list(merged.values())
        events.sort(key=lambda item: (item.get("published_at", ""), item.get("observed_at", "")), reverse=True)

        working["events"] = events[:360]
        working["source_statuses"] = source_statuses
        working["errors"] = errors[-16:]
        working["last_updated"] = utc_now()
        working["refresh_in_progress"] = False
        with STATE_LOCK:
            STATE.clear()
            STATE.update(working)
            snapshot = json.loads(json.dumps(STATE, ensure_ascii=False))
        persist_state(snapshot)
    finally:
        REFRESH_LOCK.release()


def refresh_loop():
    while True:
        refresh_all()
        time.sleep(REFRESH_SECONDS)


def dashboard_payload():
    with STATE_LOCK:
        snapshot = json.loads(json.dumps(STATE, ensure_ascii=False))
    # Publish the complete source board immediately, even while the first
    # network collection is still running.  This avoids an empty UI when an
    # overseas RSS endpoint is slow or temporarily unavailable.
    known_statuses = snapshot.get("source_statuses", {})
    statuses = []
    for source in RSS_SOURCES + SCHEDULED_SOURCES + REGISTERED_SOURCES:
        if source["id"] not in VISIBLE_SOURCE_IDS:
            continue
        current = base_source_status(source, snapshot)
        previous = known_statuses.get(source["id"], {})
        for field in ("last_attempt", "last_success", "article_count", "error"):
            if field in previous:
                current[field] = previous[field]
        if previous.get("state"):
            current["state"] = previous["state"]
        statuses.append(current)
    statuses.sort(key=lambda item: (item.get("tier", ""), item.get("name", "")))
    snapshot["sources"] = statuses
    snapshot["events"] = [event for event in snapshot.get("events", []) if event.get("source_id") in VISIBLE_SOURCE_IDS]
    try:
        snapshot["ai_digest"] = json.loads(AI_DIGEST_PATH.read_text(encoding="utf-8")) if AI_DIGEST_PATH.exists() else None
    except (OSError, ValueError):
        snapshot["ai_digest"] = None
    try:
        snapshot["douyin_live"] = json.loads(DOUYIN_LIVE_PATH.read_text(encoding="utf-8")) if DOUYIN_LIVE_PATH.exists() else None
    except (OSError, ValueError):
        snapshot["douyin_live"] = None
    snapshot["server_time"] = utc_now()
    return snapshot


def read_json_file(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def history_record_id(record):
    video_id = str((record or {}).get("video_id", "")).strip()
    if video_id.isdigit():
        return video_id
    match = re.search(r"/video/(\d+)", str((record or {}).get("url", "")))
    return match.group(1) if match else ""


def archive_history_record(record, overwrite=False):
    video_id = history_record_id(record)
    if not video_id or not isinstance(record, dict) or not record.get("title"):
        return False
    DOUYIN_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    target = DOUYIN_HISTORY_DIR / (video_id + ".json")
    if target.exists() and not overwrite:
        return False
    archived = dict(record)
    archived["video_id"] = video_id
    archived.setdefault("source", "全球速探（抖音）")
    archived.setdefault("archived_at", utc_now())
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(archived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(target))
    return True


def seed_douyin_history():
    """Recover only records already stored by this application."""
    current = read_json_file(DOUYIN_LIVE_PATH, {})
    archive_history_record(current)
    digest = read_json_file(AI_DIGEST_PATH, {})
    if not isinstance(digest, dict) or not digest.get("source_title"):
        return
    source_record = {
        "source": "全球速探（抖音）",
        "url": digest.get("source_url", ""),
        "title": digest.get("source_title", ""),
        "excerpt": digest.get("source_excerpt", ""),
        "transcript": digest.get("source_excerpt", ""),
        "transcript_type": "historical_excerpt",
        "ai_overview": digest.get("source_overview", ""),
        "ai_news_items": digest.get("source_news_items", []),
        "ai_full_transcript": digest.get("source_full_transcript", ""),
        "published_at": digest.get("source_published_at", ""),
        "checked_at": digest.get("evidence_updated_at") or digest.get("updated_at", ""),
        "archive_origin": "saved_ai_digest",
        "quality_ok": True,
    }
    archive_history_record(source_record)


def history_index_payload():
    records = []
    if DOUYIN_HISTORY_DIR.exists():
        for path in DOUYIN_HISTORY_DIR.glob("*.json"):
            record = read_json_file(path, {})
            video_id = history_record_id(record)
            if not video_id or not record.get("title"):
                continue
            items = record.get("ai_news_items") if isinstance(record.get("ai_news_items"), list) else []
            records.append({
                "video_id": video_id,
                "title": record.get("title", ""),
                "url": record.get("url", ""),
                "published_at": record.get("published_at", ""),
                "checked_at": record.get("checked_at", ""),
                "archived_at": record.get("archived_at", ""),
                "overview": record.get("ai_overview", ""),
                "news_count": len(items),
                "has_transcript": bool(record.get("ai_full_transcript") or record.get("transcript") or record.get("excerpt")),
                "source_mode": record.get("ai_source_mode") or record.get("transcript_type", ""),
            })
    records.sort(key=lambda item: (item.get("published_at", ""), item.get("checked_at", ""), item.get("video_id", "")), reverse=True)
    return {"count": len(records), "records": records, "server_time": utc_now()}


def history_detail_payload(video_id):
    if not re.match(r"^\d+$", video_id or ""):
        return None
    record = read_json_file(DOUYIN_HISTORY_DIR / (video_id + ".json"), None)
    if not isinstance(record, dict) or history_record_id(record) != video_id:
        return None
    return record


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class AppHandler(BaseHTTPRequestHandler):
    server_version = "MarketIntel/0.1"

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.address_string(), format_string % args))

    def common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'")

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, request_path):
        path = unquote(request_path).lstrip("/")
        if not path:
            path = "index.html"
        candidate = (STATIC_DIR / path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not candidate.is_file():
            candidate = STATIC_DIR / "index.html"
        try:
            body = candidate.read_bytes()
        except OSError:
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if candidate.suffix in (".html", ".js", ".css"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            payload = dashboard_payload()
            delayed = [source["name"] for source in payload["sources"] if source.get("state") == "延迟"]
            self.send_json({
                "status": "degraded" if delayed else "ok",
                "version": APP_VERSION,
                "server_time": payload["server_time"],
                "last_updated": payload.get("last_updated"),
                "delayed_sources": delayed,
            })
            return
        if path == "/api/dashboard":
            self.send_json(dashboard_payload())
            return
        if path == "/api/history":
            self.send_json(history_index_payload())
            return
        history_match = re.match(r"^/api/history/(\d+)$", path)
        if history_match:
            record = history_detail_payload(history_match.group(1))
            self.send_json(record if record is not None else {"error": "history record not found"}, 200 if record is not None else 404)
            return
        if path.startswith("/api/history/"):
            self.send_json({"error": "history record not found"}, 404)
            return
        self.serve_file(path)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seed_douyin_history()
    worker = threading.Thread(target=refresh_loop, name="collector", daemon=True)
    worker.start()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print("Market intelligence terminal listening on http://%s:%s" % (HOST, PORT))
    server.serve_forever()


if __name__ == "__main__":
    main()
