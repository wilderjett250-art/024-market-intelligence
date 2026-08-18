"""Build a twice-daily, source-faithful digest from the main multi-source feed."""
from __future__ import print_function

import html
import json
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import mktime_tz, parsedate_tz
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).resolve()
OUTPUT_PATH = DATA_DIR / "ai_digest.json"
CACHE_PATH = DATA_DIR / "cache.json"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()
ARK_API_KEY = os.environ.get("ARK_API_KEY", "").strip()
ARK_RESPONSES_API_URL = os.environ.get("ARK_RESPONSES_API_URL", "https://ark.cn-beijing.volces.com/api/v3/responses").strip()
ARK_TEXT_MODEL = os.environ.get("ARK_TEXT_MODEL", os.environ.get("ARK_VIDEO_MODEL", "doubao-seed-2-0-lite-260428")).strip()
DOUYIN_PROFILE_URL = os.environ.get("DOUYIN_PROFILE_URL", "").strip()
DOUYIN_EXCERPT_PATH = os.environ.get("DOUYIN_EXCERPT_PATH", "").strip()
DOUYIN_LIVE_PATH = DATA_DIR / "douyin_live.json"
AUTHOR_NAME = "\u5168\u7403\u901f\u63a2"
DOUYIN_LABEL = "\u5168\u7403\u901f\u63a2\uff08\u6296\u97f3\uff09"
MULTI_LABEL = "\u591a\u6e90\u7efc\u5408 AI \u7b80\u62a5"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
TOPIC_SPECS = [
    {
        "title": "影响美联储加息减息预期的消息",
        "question": "近24小时内影响美联储加息减息预期的消息",
        "details": ["通胀与经济数据", "就业与增长数据", "美联储官员表态", "市场利率预期"],
    },
    {
        "title": "期货与产业股票利多利空",
        "question": "近24小时内银、锡、碳酸锂、原油期货，商业航天、内存、人形机器人、核电股票有哪些明显的利空利多消息",
        "details": [
            "白银期货", "锡期货", "碳酸锂期货", "原油期货",
            "商业航天股票", "内存股票", "人形机器人股票", "核电股票",
        ],
    },
    {
        "title": "中东兵力、通航与美国科技股",
        "question": "近24小时美军在中东的增减兵力动态，美国伊朗动态，霍尔木兹通航量变化，美国科技股价的变化",
        "details": ["美军中东兵力", "美国伊朗动态", "霍尔木兹通航量", "美国科技股价格"],
    },
]
TOPICS = [item["title"] for item in TOPIC_SPECS]
TARGETED_FEEDS = [
    {
        "name": "Federal Reserve",
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "keywords": [],
    },
    {
        "name": "Federal Reserve Speeches",
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "keywords": ["inflation", "employment", "economy", "economic", "monetary", "interest rate", "policy"],
    },
    {
        "name": "CNBC Markets",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "keywords": ["fed", "rate", "inflation", "cpi", "pce", "payroll", "jobs", "employment", "unemployment", "wage", "gdp", "growth", "treasury", "yield", "futures", "silver", "tin", "lithium", "oil", "space", "memory", "chip", "robot", "nuclear", "nvidia", "tesla", "tech"],
    },
    {
        "name": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
        "keywords": ["fed", "rate", "inflation", "cpi", "pce", "payroll", "jobs", "employment", "unemployment", "wage", "gdp", "growth", "treasury", "yield", "futures", "silver", "tin", "lithium", "oil", "space", "memory", "chip", "robot", "nuclear", "nvidia", "tesla", "tech"],
    },
    {
        "name": "SpaceNews",
        "url": "https://spacenews.com/feed/",
        "keywords": [],
        "labels": ["商业航天股票"],
    },
    {
        "name": "Tom's Hardware",
        "url": "https://www.tomshardware.com/feeds/all",
        "keywords": ["memory", "dram", "nand", "hbm", "chip", "semiconductor", "nvidia", "robot"],
    },
    {
        "name": "Nuclear Newswire",
        "url": "https://www.ans.org/news/feed/",
        "keywords": [],
        "labels": ["核电股票"],
    },
    {
        "name": "Electrek",
        "url": "https://electrek.co/feed/",
        "keywords": ["tesla", "robot", "optimus", "nvidia", "technology"],
    },
    {
        "name": "WSJ Markets",
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "keywords": ["fed", "rate", "inflation", "jobs", "yield", "futures", "silver", "tin", "lithium", "oil", "nvidia", "tesla", "technology"],
    },
    {
        "name": "OilPrice.com",
        "url": "https://oilprice.com/rss/main",
        "keywords": ["oil", "crude", "opec", "iran", "hormuz", "tanker", "shipping"],
        "labels": ["原油期货"],
    },
    {
        "name": "Defense News",
        "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/mideast-africa/?outputType=xml",
        "keywords": ["iran", "middle east", "centcom", "troop", "base", "gulf", "hormuz", "israel", "houthi"],
    },
    {
        "name": "Space.com",
        "url": "https://www.space.com/feeds/all",
        "keywords": ["launch", "rocket", "satellite", "spacex", "blue origin", "contract", "commercial"],
        "labels": ["商业航天股票"],
    },
]
SINA_QUOTES_URL = "https://hq.sinajs.cn/list=hf_SI,hf_CL,nf_SN0,nf_LC0,gb_nvda,gb_tsla"
CHANGE_VALUES = [
    "\u589e\u52a0", "\u51cf\u5c11", "\u5347\u7ea7", "\u7f13\u548c",
    "\u4e0a\u6da8", "\u4e0b\u8dcc", "\u5229\u591a", "\u5229\u7a7a", "\u4e2d\u6027", "\u5206\u5316", "\u672a\u63d0\u53ca", "\u5f85\u786e\u8ba4",
]
COVERAGE_KEYWORDS = {
    "通胀与经济数据": ["inflation", "cpi", "pce", "consumer prices", "gdp", "economic growth"],
    "就业与增长数据": ["employment", "nonfarm payroll", "unemployment", "jobs report", "jobless claims", "labor market", "gdp", "economic growth"],
    "美联储官员表态": ["federal reserve", "fomc", "fed chair", "powell", "fed governor", "fed president"],
    "市场利率预期": ["rate cut", "rate hike", "interest rate", "treasury yield", "fed funds", "rate expectations"],
    "白银期货": ["silver futures", "silver price"],
    "锡期货": ["tin futures", "tin price"],
    "碳酸锂期货": ["lithium carbonate", "lithium futures", "lithium price"],
    "原油期货": ["crude oil", "oil futures", "brent", "wti", "opec"],
    "商业航天股票": ["commercial space", "spacex", "blue origin", "rocket launch", "satellite contract", "space force contract"],
    "内存股票": ["dram", "nand", "hbm", "memory chip", "memory prices", "ddr5"],
    "人形机器人股票": ["humanoid robot", "optimus", "humanoid robotics stock"],
    "核电股票": ["nuclear power", "nuclear plant", "nuclear reactor", "uranium", "fusion energy"],
    "美军中东兵力": ["centcom", "u.s. military", "us military", "troop deployment", "military base", "task force"],
    "美国伊朗动态": ["u.s. iran", "us iran", "iran sanctions", "tehran", "iran talks"],
    "霍尔木兹通航量": ["strait of hormuz", "hormuz traffic", "hormuz shipping", "hormuz tanker"],
    "美国科技股价格": ["nvidia stock", "tesla stock", "nasdaq", "technology stocks", "tech stocks"],
}
FED_DETAIL_LABELS = {"通胀与经济数据", "就业与增长数据", "美联储官员表态", "市场利率预期"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_timestamp(value):
    """Parse the feed ISO timestamps on the server's older platform Python."""
    text = clean_text(value)
    match = re.match(
        r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$",
        text,
    )
    if not match:
        raise ValueError("invalid ISO timestamp")
    parsed = datetime.strptime(match.group(1) + "T" + match.group(2), "%Y-%m-%dT%H:%M:%S")
    offset = match.group(3) or "Z"
    if offset == "Z":
        zone = timezone.utc
    else:
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        zone = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    return parsed.replace(tzinfo=zone).timestamp()


def request_text(url, timeout=25):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    with urlopen(Request(url, headers=headers), timeout=timeout) as response:
        return response.geturl(), response.read().decode("utf-8", "replace")


def clean_text(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def request_bytes(url, timeout=15, headers=None, limit=2 * 1024 * 1024):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml,application/xml,text/xml,application/json,text/plain,*/*",
    }
    if headers:
        request_headers.update(headers)
    with urlopen(Request(url, headers=request_headers), timeout=timeout) as response:
        return response.read(limit)


def local_name(tag):
    return str(tag).rsplit("}", 1)[-1].lower()


def feed_child_text(node, names):
    wanted = set(names)
    for child in list(node):
        if local_name(child.tag) in wanted:
            value = clean_text("".join(child.itertext()))
            if value:
                return value
    return ""


def feed_link(node):
    for child in list(node):
        if local_name(child.tag) != "link":
            continue
        href = clean_text(child.attrib.get("href", ""))
        value = href or clean_text("".join(child.itertext()))
        if value.startswith(("http://", "https://")):
            return value
    return ""


def feed_time(value):
    text = clean_text(value)
    try:
        return iso_timestamp(text)
    except (AttributeError, TypeError, ValueError):
        parsed = parsedate_tz(text)
        if not parsed:
            raise ValueError("invalid feed timestamp")
        return float(mktime_tz(parsed))


def inferred_coverage_labels(title, summary, source=""):
    corpus = (clean_text(title) + " " + clean_text(summary)).lower()
    source_text = clean_text(source).lower()
    us_rate_context = any(term in corpus for term in (
        "federal reserve", "fomc", "fed chair", "fed governor", "fed president",
        "u.s.", "united states", "us inflation", "us jobs", "american economy", "treasury yield",
    )) or source_text.startswith("federal reserve")
    labels = []
    for label, terms in COVERAGE_KEYWORDS.items():
        if not any(term in corpus for term in terms):
            continue
        if label in FED_DETAIL_LABELS and not us_rate_context:
            continue
        labels.append(label)
    return labels


def fetch_targeted_feed(feed):
    root = ET.fromstring(request_bytes(feed["url"]))
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 24 * 60 * 60
    keywords = [item.lower() for item in feed.get("keywords", [])]
    events = []
    for node in root.iter():
        if local_name(node.tag) not in {"item", "entry"}:
            continue
        title = feed_child_text(node, {"title"})
        link = feed_link(node)
        summary = feed_child_text(node, {"description", "summary", "content", "encoded"})[:420]
        published_text = feed_child_text(node, {"pubdate", "published", "updated", "date"})
        if not title or not link or not published_text:
            continue
        try:
            published = feed_time(published_text)
        except ValueError:
            continue
        if published < cutoff or published > now + 6 * 60 * 60:
            continue
        corpus = (title + " " + summary).lower()
        if keywords and not any(keyword in corpus for keyword in keywords):
            continue
        coverage_labels = list(feed.get("labels", []))
        for label in inferred_coverage_labels(title, summary, feed["name"]):
            if label not in coverage_labels:
                coverage_labels.append(label)
        published_at = datetime.fromtimestamp(published, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        events.append({
            "title": title[:260],
            "summary": summary,
            "source": feed["name"],
            "published_at": published_at,
            "url": link,
            "coverage_labels": coverage_labels,
        })
    events.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return events[:8]


def targeted_context():
    events = []
    errors = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_targeted_feed, feed): feed for feed in TARGETED_FEEDS}
        for future in as_completed(futures):
            feed = futures[future]
            try:
                events.extend(future.result())
            except Exception as exc:
                errors.append({"source": feed["name"], "error": clean_text(str(exc))[:140]})
    unique = {}
    for item in events:
        unique[item["url"]] = item
    ordered = sorted(unique.values(), key=lambda item: item.get("published_at", ""), reverse=True)
    return {"events": ordered[:64], "errors": errors}


def publisher_name(value):
    hostname = (urlparse(value).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or "公开网络来源"


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def quote_summary(label, name, current, previous, source_url, observed_text):
    if current is None or previous in {None, 0}:
        return None
    percent = (current - previous) / previous * 100
    change = "上涨" if percent > 0.01 else "下跌" if percent < -0.01 else "中性"
    return {
        "label": label,
        "name": name,
        "value": current,
        "previous": previous,
        "change_percent": round(percent, 2),
        "change": change,
        "summary": "%s最新价 %s，较上一结算/收盘%s %.2f%%。" % (
            name,
            ("%.4f" % current).rstrip("0").rstrip("."),
            "上涨" if percent > 0 else "下跌" if percent < 0 else "持平",
            abs(percent),
        ),
        "observed_at": observed_text,
        "source": "新浪财经行情",
        "source_url": source_url,
    }


def market_snapshot_context():
    body = request_bytes(
        SINA_QUOTES_URL,
        headers={"Referer": "https://finance.sina.com.cn/", "Accept": "application/javascript,*/*"},
    ).decode("gb18030", "replace")
    raw_quotes = {
        match.group(1): match.group(2).split(",")
        for match in re.finditer(r'var\s+hq_str_([A-Za-z0-9_]+)="([^"]*)";', body)
    }
    snapshots = []
    global_specs = {
        "hf_SI": ("白银期货", "纽约白银", "https://finance.sina.com.cn/futures/quotes/SI.shtml"),
        "hf_CL": ("原油期货", "纽约原油", "https://finance.sina.com.cn/futures/quotes/CL.shtml"),
    }
    for code, (label, name, source_url) in global_specs.items():
        parts = raw_quotes.get(code, [])
        if len(parts) < 14:
            continue
        snapshot = quote_summary(label, parts[13] or name, number(parts[0]), number(parts[7]), source_url, (parts[12] + " " + parts[6]).strip())
        if snapshot:
            snapshots.append(snapshot)
    domestic_specs = {
        "nf_SN0": ("锡期货", "锡连续", "https://finance.sina.com.cn/futures/quotes/SN0.shtml"),
        "nf_LC0": ("碳酸锂期货", "碳酸锂连续", "https://finance.sina.com.cn/futures/quotes/LC0.shtml"),
    }
    for code, (label, name, source_url) in domestic_specs.items():
        parts = raw_quotes.get(code, [])
        if len(parts) < 18:
            continue
        snapshot = quote_summary(label, parts[0] or name, number(parts[8]), number(parts[10]), source_url, (parts[17] + " " + parts[1]).strip())
        if snapshot:
            snapshots.append(snapshot)
    us_specs = {
        "gb_nvda": ("英伟达 NVDA", "https://finance.sina.com.cn/stock/usstock/quotes/NVDA.html"),
        "gb_tsla": ("特斯拉 TSLA", "https://finance.sina.com.cn/stock/usstock/quotes/TSLA.html"),
    }
    for code, (name, source_url) in us_specs.items():
        parts = raw_quotes.get(code, [])
        if len(parts) < 5:
            continue
        current = number(parts[1])
        percent = number(parts[2])
        if current is None or percent is None:
            continue
        snapshots.append({
            "label": "美国科技股价格",
            "name": name,
            "value": current,
            "change_percent": round(percent, 2),
            "change": "上涨" if percent > 0.01 else "下跌" if percent < -0.01 else "中性",
            "summary": "%s最新价 %s，涨跌幅 %+.2f%%。" % (name, ("%.4f" % current).rstrip("0").rstrip("."), percent),
            "observed_at": parts[3],
            "source": "新浪财经行情",
            "source_url": source_url,
        })
    return snapshots


def text_values(value, output):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"desc", "description", "title", "text", "content", "chapter", "caption"} and isinstance(item, str):
                cleaned = clean_text(item)
                if len(cleaned) >= 12:
                    output.append(cleaned)
            text_values(item, output)
    elif isinstance(value, list):
        for item in value:
            text_values(item, output)


def extract_page_text(page):
    candidates = []
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    description = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']', page, re.I | re.S)
    for match in (title, description):
        if match:
            candidates.append(clean_text(match.group(1)))
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            text_values(json.loads(raw), candidates)
        except (TypeError, ValueError):
            pass
    unique = []
    for item in candidates:
        if item and item not in unique:
            unique.append(item)
    return unique[:12]


def douyin_context():
    candidate_paths = [DOUYIN_LIVE_PATH]
    if DOUYIN_EXCERPT_PATH:
        candidate_paths.append(Path(DOUYIN_EXCERPT_PATH))
    for candidate_path in candidate_paths:
        try:
            saved = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
            title = clean_text(saved.get("title", ""))
            excerpt = clean_text(saved.get("excerpt", ""))
            valid_title = bool(re.search(r"^第\s*\d+\s*集.*全球局势速看", title))
            if saved.get("url") and (valid_title or "章节要点" in excerpt):
                return {
                    "status": "ok",
                    "url": saved["url"],
                    "records": [{
                        "title": title[:300] or (AUTHOR_NAME + "\u516c\u5f00\u4f5c\u54c1"),
                        "excerpt": excerpt[:30000],
                        "transcript": clean_text(saved.get("transcript", excerpt))[:30000],
                        "transcript_type": saved.get("transcript_type", "douyin_public_chapters"),
                        "ai_overview": clean_text(saved.get("ai_overview", ""))[:500],
                        "ai_news_items": saved.get("ai_news_items", [])[:12] if isinstance(saved.get("ai_news_items"), list) else [],
                        "ai_full_transcript": saved.get("ai_full_transcript", ""),
                        "published_at": saved.get("published_at", ""),
                    }],
                }
        except (OSError, ValueError, TypeError):
            pass
    if not DOUYIN_PROFILE_URL:
        return {"status": "missing", "url": "", "records": [], "reason": "\u672a\u914d\u7f6e\u6296\u97f3\u516c\u5f00\u4e3b\u9875\u94fe\u63a5"}
    try:
        final_url, page = request_text(DOUYIN_PROFILE_URL)
        extracted = extract_page_text(page)
        combined = " ".join(extracted)
        if AUTHOR_NAME not in combined and "/user/" not in DOUYIN_PROFILE_URL:
            return {"status": "unverified", "url": final_url, "records": [], "reason": "\u516c\u5f00\u9875\u672a\u80fd\u9a8c\u8bc1\u4f5c\u8005"}
        if not extracted:
            return {"status": "empty", "url": final_url, "records": [], "reason": "\u516c\u5f00\u9875\u6ca1\u6709\u53ef\u6458\u5f55\u6587\u5b57"}
        return {"status": "ok", "url": final_url, "records": [{"title": extracted[0][:300], "excerpt": "\n".join(extracted[:8])[:30000], "transcript": "\n".join(extracted[:8])[:30000], "transcript_type": "public_page_text"}]}
    except Exception as exc:
        return {"status": "error", "url": DOUYIN_PROFILE_URL, "records": [], "reason": str(exc)[:160]}


def multi_source_context():
    """Read the persisted main feed so the digest is genuinely multi-source."""
    try:
        state = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "empty", "events": [], "metrics": [], "source_count": 0, "updated_at": ""}

    events = sorted(
        state.get("events") or [],
        key=lambda item: (item.get("published_at", ""), item.get("observed_at", "")),
        reverse=True,
    )
    records = []
    source_names = set()
    for event in events[:120]:
        title = clean_text(event.get("title_original") or event.get("title", ""))[:260]
        summary = clean_text(event.get("summary", ""))[:360]
        url = (event.get("url") or "").strip()
        if not title or not url:
            continue
        source = clean_text(event.get("source", ""))
        source_names.add(source)
        records.append({
            "title": title,
            "summary": summary,
            "source": source,
            "published_at": event.get("published_at", ""),
            "url": url,
            "commodities": event.get("commodities", []),
            "factors": event.get("factors", []),
        })
    metrics = []
    for metric in (state.get("metrics") or [])[:20]:
        metrics.append({
            "name": metric.get("name", ""),
            "commodity": metric.get("commodity", ""),
            "value": metric.get("value"),
            "unit": metric.get("unit", ""),
            "delta": metric.get("delta"),
            "period": metric.get("period", ""),
            "source": metric.get("source", ""),
            "source_url": metric.get("source_url", ""),
        })
    # Put topic-relevant evidence first and keep the prompt compact enough for a fast scheduled run.
    keywords = (
        "iran", "israel", "houth", "hormuz", "red sea", "middle east", "military", "troop", "base",
        "tanker", "shipping", "strait", "attack", "strike", "ceasefire", "saudi", "trump", "netanyahu",
        "oil", "brent", "wti", "silver", "tin", "lithium", "carbonate", "federal reserve", "fed", "rate",
        "hike", "cut", "hawkish", "dovish", "nvidia", "tesla", "spacex", "space", "memory", "robot", "nuclear", "stock",
    )
    def relevance(item):
        haystack = (item.get("title", "") + " " + item.get("summary", "")).lower()
        return sum(1 for keyword in keywords if keyword in haystack)
    all_records = records
    cutoff = datetime.now(timezone.utc).timestamp() - 24 * 60 * 60
    recent_candidates = []
    for item in all_records:
        try:
            published = iso_timestamp(item.get("published_at", ""))
        except (AttributeError, ValueError, TypeError):
            continue
        if published >= cutoff:
            recent_candidates.append(item)
    records = sorted(all_records, key=lambda item: (relevance(item), item.get("published_at", "")), reverse=True)[:48]
    recent_events = sorted(
        recent_candidates,
        key=lambda item: (relevance(item), item.get("published_at", "")),
        reverse=True,
    )[:48]
    return {
        "status": "ok" if records or metrics else "empty",
        "events": records,
        "recent_events": recent_events[:36],
        "metrics": metrics,
        "source_count": len([name for name in source_names if name]),
        "updated_at": state.get("last_updated", ""),
    }


def default_topics(source_url=""):
    summary = "\u672c\u8f6e\u591a\u6e90\u8bc1\u636e\u4e2d\u6682\u65e0\u53ef\u6838\u5b9e\u7684\u660e\u786e\u53d8\u5316\u3002"
    return [{
        "title": spec["title"],
        "question": spec["question"],
        "summary": summary,
        "change": "\u5f85\u786e\u8ba4",
        "sources": [source_url] if source_url else [],
        "details": [{
            "label": label,
            "summary": "近24小时内未找到可核实的明确变化。",
            "change": "未提及",
            "sources": [],
        } for label in spec["details"]],
    } for spec in TOPIC_SPECS]


def evidence_catalog(context):
    rows = []
    by_url = {}

    def add_event(item, kind):
        url = clean_text(item.get("url") or item.get("source_url"))
        if not url:
            return
        labels = [clean_text(label) for label in item.get("coverage_labels", []) if clean_text(label)]
        for label in inferred_coverage_labels(item.get("title") or item.get("name"), item.get("summary"), item.get("source")):
            if label not in labels:
                labels.append(label)
        if url in by_url:
            row = by_url[url]
            for label in labels:
                if label not in row["coverage_labels"]:
                    row["coverage_labels"].append(label)
            return
        row = {
            "id": "E%03d" % (len(rows) + 1),
            "title": clean_text(item.get("title") or item.get("name"))[:260],
            "summary": clean_text(item.get("summary"))[:420],
            "source": clean_text(item.get("source")) or publisher_name(url),
            "kind": clean_text(item.get("source_kind")) or kind,
            "published_at": clean_text(item.get("published_at") or item.get("observed_at"))[:60],
            "url": url,
            "coverage_labels": labels,
            "change": clean_text(item.get("change")),
        }
        rows.append(row)
        by_url[url] = row

    for item in context.get("recent_events", []):
        add_event(item, "主信息流")
    for item in context.get("targeted_events", []):
        add_event(item, "专题公开来源")
    for item in context.get("broad_events", []):
        add_event(item, "公开新闻检索")
    for item in context.get("market_snapshots", []):
        snapshot = dict(item)
        snapshot["title"] = snapshot.get("name") or snapshot.get("label")
        snapshot["coverage_labels"] = [snapshot.get("label", "")]
        snapshot["source_kind"] = "行情数据"
        add_event(snapshot, "行情数据")
    return rows


def source_reference(row):
    return {
        "id": row.get("id", ""),
        "name": row.get("source", "") or publisher_name(row.get("url", "")),
        "url": row.get("url", ""),
        "kind": row.get("kind", ""),
        "published_at": row.get("published_at", ""),
    }


def source_level(refs):
    domains = {urlparse(ref.get("url", "")).hostname for ref in refs if ref.get("url")}
    domains.discard(None)
    if len(domains) >= 2:
        return "多方来源"
    if refs and all(ref.get("kind") == "行情数据" for ref in refs):
        return "行情数据"
    return "单一来源线索" if refs else "暂无来源"


def source_backed_topics(context):
    """Build a useful cited table even when the model response is unavailable."""
    catalog = evidence_catalog(context)
    topics = []
    for spec in TOPIC_SPECS:
        topic_rows = []
        details = []
        for label in spec["details"]:
            candidates = [row for row in catalog if label in row.get("coverage_labels", [])]
            candidates.sort(key=lambda row: (row.get("kind") == "行情数据", row.get("published_at", "")), reverse=True)
            selected = []
            domains = set()
            for row in candidates:
                domain = urlparse(row.get("url", "")).hostname or row.get("source", "")
                if domain in domains and selected:
                    continue
                selected.append(row)
                domains.add(domain)
                if len(selected) >= 2:
                    break
            refs = [source_reference(row) for row in selected]
            if selected:
                pieces = []
                for row in selected:
                    text = row.get("title", "")
                    if row.get("summary") and row.get("summary") not in text:
                        text += "：" + row["summary"]
                    if text:
                        pieces.append(text)
                summary = "；".join(pieces)[:300]
                changes = {row.get("change") for row in selected if row.get("change") in CHANGE_VALUES}
                change = next(iter(changes)) if len(changes) == 1 else "待确认"
            else:
                summary = "近24小时公开检索暂未发现直接相关信息。"
                change = "未提及"
            details.append({
                "label": label,
                "summary": summary,
                "change": change,
                "sources": [ref["url"] for ref in refs],
                "source_refs": refs,
                "source_level": source_level(refs),
            })
            for row in selected:
                if row not in topic_rows:
                    topic_rows.append(row)
        refs = [source_reference(row) for row in topic_rows[:8]]
        topics.append({
            "title": spec["title"],
            "question": spec["question"],
            "summary": "本轮收集到 %d 条带来源的公开信息；未确认线索已单独标记。" % len(topic_rows) if topic_rows else "本轮公开检索暂未发现直接相关信息。",
            "change": "待确认",
            "sources": [ref["url"] for ref in refs],
            "source_refs": refs,
            "source_level": source_level(refs),
            "details": details,
        })
    return topics


def extract_json_response(content):
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


def ark_response_text(data):
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


def provider_request(provider, prompt):
    if provider == "deepseek":
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DeepSeek credential unavailable")
        payload = json.dumps({
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 5200,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        request = Request(DEEPSEEK_API_URL, data=payload, headers={
            "Authorization": "Bearer " + DEEPSEEK_API_KEY,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        with urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return extract_json_response(content), data, DEEPSEEK_MODEL

    if provider == "doubao":
        if not ARK_API_KEY:
            raise RuntimeError("Doubao credential unavailable")
        payload = json.dumps({
            "model": ARK_TEXT_MODEL,
            "input": [{
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }],
            "thinking": {"type": "disabled"},
            "max_output_tokens": 5200,
        }).encode("utf-8")
        request = Request(ARK_RESPONSES_API_URL, data=payload, headers={
            "Authorization": "Bearer " + ARK_API_KEY,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        with urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        return extract_json_response(ark_response_text(data)), data, ARK_TEXT_MODEL

    raise ValueError("Unknown AI provider")


def provider_json_with_retry(provider, prompt):
    last_error = None
    for attempt in range(2):
        current_prompt = prompt
        if attempt:
            current_prompt += (
                "\n\nThe previous response was incomplete or invalid JSON. Return a shorter valid JSON object now. "
                "Keep every required detail row, limit each detail summary to 90 Chinese characters, and use short evidence IDs only."
            )
        try:
            return provider_request(provider, current_prompt)
        except HTTPError as exc:
            last_error = exc
            if 400 <= exc.code < 500:
                break
        except (ValueError, TypeError, OSError) as exc:
            last_error = exc
    raise RuntimeError("%s unavailable: %s" % (provider, clean_text(last_error)[:140]))


def routed_ai_request(prompt):
    errors = []
    if DEEPSEEK_API_KEY:
        try:
            result, data, model = provider_json_with_retry("deepseek", prompt)
            return result, data, "deepseek", model, False, ""
        except Exception as exc:
            errors.append("DeepSeek: " + clean_text(exc)[:140])
    else:
        errors.append("DeepSeek: credential unavailable")

    if ARK_API_KEY:
        try:
            result, data, model = provider_json_with_retry("doubao", prompt)
            return result, data, "doubao", model, True, "; ".join(errors)
        except Exception as exc:
            errors.append("Doubao: " + clean_text(exc)[:140])
    else:
        errors.append("Doubao: credential unavailable")
    raise RuntimeError("All AI providers unavailable: " + "; ".join(errors))


def call_ai(context, douyin_record=None):
    topic_specs = json.dumps(TOPIC_SPECS, ensure_ascii=False)
    catalog = evidence_catalog(context)
    evidence_by_id = {item["id"]: item for item in catalog}
    evidence_by_url = {item["url"]: item for item in catalog}
    prompt_catalog = [{
        "id": item["id"],
        "title": item["title"],
        "summary": item["summary"],
        "source": item["source"],
        "kind": item["kind"],
        "published_at": item["published_at"],
        "coverage_labels": item["coverage_labels"],
        "change": item["change"],
    } for item in catalog]
    evidence = json.dumps({
        "status": context.get("status", "empty"),
        "source_count": context.get("source_count", 0),
        "updated_at": context.get("updated_at", ""),
        "evidence": prompt_catalog,
    }, ensure_ascii=False)
    douyin_record = douyin_record or {}
    transcript = clean_text(douyin_record.get("transcript", douyin_record.get("excerpt", "")))
    transcript_type = clean_text(douyin_record.get("transcript_type", ""))
    transcript_available = bool(transcript) and transcript_type in {"local_vosk_asr", "douyin_public_chapters", "public_page_text"}
    refined_items = douyin_record.get("ai_news_items", []) if isinstance(douyin_record.get("ai_news_items"), list) else []
    douyin_evidence = {
        "title": clean_text(douyin_record.get("title", ""))[:260],
        "published_at": douyin_record.get("published_at", ""),
        "url": douyin_record.get("url", ""),
        "transcript_available": transcript_available,
        "transcript_type": transcript_type or "unknown",
        "transcript": transcript[:12000] if transcript_available and not refined_items else "",
        "refined_overview": clean_text(douyin_record.get("ai_overview", ""))[:500],
        "refined_news_items": refined_items[:12],
    }
    prompt = (
        "You are a Chinese market and geopolitical intelligence editor. "
        "Use all relevant supplied public evidence, including official statements, mainstream media, regional or industry outlets, social-media reports, and unverified reports. "
        "Do not discard a relevant report only because its source is not authoritative. Do not add outside news, prices, inventories, common knowledge, or guesses. "
        "If a report is a rumor, a single-source claim, or not independently confirmed, include it when relevant but clearly prefix its summary with [未证实]. "
        "If sources conflict, preserve the disagreement and never present one source claim as verified fact. "
        "Answer the three scheduled questions for the latest 24 hours in concise Chinese. "
        "The change field must be one of: " + json.dumps(CHANGE_VALUES, ensure_ascii=False) + ". "
        "Return JSON only with exactly three topic objects in this order: " + topic_specs + ". "
        "For all three topics, use only the supplied evidence catalog. Every catalog row is already limited to the requested time window. "
        "Topic 1 covers news that can change Federal Reserve rate-hike or rate-cut expectations: inflation data, employment and growth data, Federal Reserve officials' guidance, Treasury yields, and market-implied rate expectations. Do not require a formal Federal Reserve rate decision. "
        "Topic 2 covers silver, tin, lithium carbonate and crude-oil futures, plus commercial space, memory, humanoid-robot and nuclear-power stocks. "
        "Topic 3 covers US troop increases or withdrawals in the Middle East, developments between the United States and Iran, changes in Strait of Hormuz traffic, and US technology-stock price changes. "
        "For Topic 1, only United States inflation, employment, growth, Federal Reserve, Treasury-yield or market-rate-expectation evidence qualifies; another country's domestic inflation alone does not qualify. "
        "For humanoid robots, exclude robotaxis, autonomous driving, industrial robots and generic robotics unless the evidence explicitly concerns humanoid robots or Optimus. "
        "For US Middle East troop levels, a new task force, exercise, strike or capability does not prove personnel increased; report the activity but keep the change as 待确认 unless the evidence explicitly states deployment, withdrawal or headcount. "
        "Each topic must contain title, summary, change, evidence_ids, and details. Summary is an overall conclusion of at most 140 Chinese characters. "
        "Details must contain every label listed in that topic's details field, exactly once and in the supplied order; no label may be omitted. "
        "Each detail contains label, summary, change, and evidence_ids. Do not suppress relevant unverified reports; label them [未证实] and cite one to three supplied evidence IDs. If a label has no relevant report at all, still return it with change 未提及, evidence_ids [], and summary 近24小时内未找到相关公开消息。 "
        "A market snapshot may prove a price rise or fall, but it does not by itself prove the cause or a bullish/bearish news event. "
        "Every factual summary or detail must cite only evidence IDs that occur in the supplied catalog. Never output URLs and never invent an evidence ID. "
        "If there is no clear evidence for an entire topic, set topic change to 待确认 and evidence_ids to [], but still return every required detail row. "
        "Also return douyin_summary as a concise Chinese paragraph of no more than 120 Chinese characters. "
        "When transcript_available is true, use refined_news_items when present, otherwise use the supplied transcript, only for douyin_summary; "
        "do not silently mix it into the three multi-source topics. When transcript_available is false, derive douyin_summary only from the supplied multi-source evidence and the work title; "
        "do not claim that the video itself said anything that is not in the evidence. If there is not enough evidence, return an empty string.\n\n"
        "Douyin public-work metadata:\n" + json.dumps(douyin_evidence, ensure_ascii=False) + "\n\n"
        "Multi-source public evidence catalog:\n" + evidence
    )
    result, data, ai_provider, ai_model, fallback_used, primary_error = routed_ai_request(prompt)
    raw_topics = result.get("topics") or result.get("items") or result.get("briefs") or []
    if isinstance(raw_topics, dict):
        raw_topics = [dict(value, title=key) if isinstance(value, dict) else {"title": key, "summary": value} for key, value in raw_topics.items()]
    if not isinstance(raw_topics, list):
        raw_topics = []
    if not raw_topics and isinstance(result, dict):
        raw_topics = [{"title": key, "summary": value} for key, value in result.items() if key not in {"status", "note"} and isinstance(value, (str, dict))]
    normalized = []

    def cited_rows(value):
        if not isinstance(value, dict):
            return []
        tokens = value.get("evidence_ids")
        if not isinstance(tokens, list):
            tokens = value.get("sources") if isinstance(value.get("sources"), list) else []
        selected = []
        for token in tokens:
            row = evidence_by_id.get(token) or evidence_by_url.get(token)
            if row and row not in selected:
                selected.append(row)
        return selected[:3]

    def label_fallback_rows(label):
        candidates = [row for row in catalog if label in row.get("coverage_labels", [])]
        candidates.sort(key=lambda row: (row.get("kind") == "行情数据", row.get("published_at", "")), reverse=True)
        selected = []
        domains = set()
        for row in candidates:
            domain = urlparse(row.get("url", "")).hostname or row.get("source", "")
            if domain in domains and len(selected) >= 1:
                continue
            selected.append(row)
            domains.add(domain)
            if len(selected) >= 2:
                break
        return selected

    for index, spec in enumerate(TOPIC_SPECS):
        title = spec["title"]
        titled = next((candidate for candidate in raw_topics if isinstance(candidate, dict) and title in clean_text(candidate.get("title", ""))), None)
        item = titled or (raw_topics[index] if index < len(raw_topics) and isinstance(raw_topics[index], dict) else {})
        # Some JSON-mode responses wrap each topic one extra level under summary.
        while isinstance(item, dict) and isinstance(item.get("summary"), dict):
            nested = item.get("summary")
            if not nested.get("summary") and not nested.get("title"):
                break
            item = nested
        topic_rows = cited_rows(item)
        details = []
        raw_details = item.get("details") if isinstance(item.get("details"), list) else []
        for required_label in spec["details"]:
            candidate = {}
            for raw_detail in raw_details:
                if not isinstance(raw_detail, dict):
                    continue
                raw_label = clean_text(raw_detail.get("label") or raw_detail.get("title"))
                if raw_label and (raw_label == required_label or required_label in raw_label or raw_label in required_label):
                    candidate = raw_detail
                    break
            detail_rows = [
                row for row in cited_rows(candidate)
                if required_label in row.get("coverage_labels", [])
            ]
            detail_summary = clean_text(candidate.get("summary", ""))[:300] if isinstance(candidate, dict) else ""
            detail_change = clean_text(candidate.get("change", "")) if isinstance(candidate, dict) else ""
            if not detail_rows:
                detail_rows = label_fallback_rows(required_label)
                if detail_rows:
                    pieces = []
                    for row in detail_rows:
                        text = row.get("title", "")
                        if row.get("summary") and row.get("summary") not in text:
                            text += "：" + row["summary"]
                        if text:
                            pieces.append(text)
                    detail_summary = "；".join(pieces)[:300]
                    snapshot_changes = {row.get("change") for row in detail_rows if row.get("kind") == "行情数据" and row.get("change") in CHANGE_VALUES}
                    detail_change = next(iter(snapshot_changes)) if len(snapshot_changes) == 1 else "待确认"
            if not detail_rows:
                detail_summary = "近24小时公开检索暂未发现直接相关信息。"
                detail_change = "未提及"
            elif detail_change not in CHANGE_VALUES:
                detail_change = "待确认"
            detail_refs = [source_reference(row) for row in detail_rows]
            details.append({
                "label": required_label,
                "summary": detail_summary or "已发现相关公开线索，请结合来源原文核对。",
                "change": detail_change,
                "sources": [ref["url"] for ref in detail_refs],
                "source_refs": detail_refs,
                "source_level": source_level(detail_refs),
            })
            for row in detail_rows:
                if row not in topic_rows:
                    topic_rows.append(row)
        change = clean_text(item.get("change", ""))
        if change not in CHANGE_VALUES:
            change = "\u5f85\u786e\u8ba4"
        summary = clean_text(item.get("summary", ""))[:180]
        if not summary and topic_rows:
            summary = "本轮收集到 %d 条带来源的公开信息，包含单一来源线索，详情见下表。" % len(topic_rows)
        if not summary:
            summary = "本轮公开检索暂未发现直接相关信息。"
        if not topic_rows:
            change = "待确认"
        topic_refs = [source_reference(row) for row in topic_rows[:8]]
        normalized.append({
            "title": title,
            "question": spec["question"],
            "summary": summary,
            "change": change,
            "sources": [ref["url"] for ref in topic_refs],
            "source_refs": topic_refs,
            "source_level": source_level(topic_refs),
            "details": details,
        })
    douyin_summary = clean_text(result.get("douyin_summary", ""))[:240]
    if transcript_available:
        douyin_summary = ""
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return {
        "topics": normalized,
        "douyin_summary": douyin_summary,
        "ai_provider": ai_provider,
        "ai_model": ai_model,
        "ai_fallback_used": fallback_used,
        "ai_primary_error": primary_error,
        "ai_usage": {
            "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
            "completion_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    multi = multi_source_context()
    try:
        targeted = targeted_context()
    except Exception as exc:
        targeted = {"events": [], "errors": [{"source": "targeted feeds", "error": clean_text(str(exc))[:140]}]}
    try:
        market_snapshots = market_snapshot_context()
    except Exception as exc:
        market_snapshots = []
        targeted.setdefault("errors", []).append({"source": "market snapshots", "error": clean_text(str(exc))[:140]})
    multi["targeted_events"] = targeted.get("events", [])
    multi["market_snapshots"] = market_snapshots
    additional_sources = {item.get("source") for item in multi["targeted_events"] if item.get("source")}
    if market_snapshots:
        additional_sources.add("新浪财经行情")
    multi["source_count"] = multi.get("source_count", 0) + len(additional_sources)
    douyin = douyin_context()
    douyin_record = douyin.get("records", [{}])[0] if douyin.get("records") else {}
    evidence_count = (
        len(multi.get("recent_events", []))
        + len(multi.get("targeted_events", []))
        + len(multi.get("market_snapshots", []))
    )
    evidence_ready = evidence_count > 0
    output = {
        "updated_at": utc_now(),
        "schedule_timezone": "Asia/Taipei",
        "source": MULTI_LABEL,
        "source_status": multi["status"],
        "source_count": multi.get("source_count", 0),
        "evidence_count": evidence_count,
        "targeted_evidence_count": len(multi.get("targeted_events", [])),
        "market_snapshot_count": len(multi.get("market_snapshots", [])),
        "collection_errors": targeted.get("errors", []),
        "evidence_updated_at": multi.get("updated_at", ""),
        "source_url": douyin.get("url", DOUYIN_PROFILE_URL),
        "source_title": douyin_record.get("title", ""),
        "source_excerpt": douyin_record.get("excerpt", ""),
        "source_overview": douyin_record.get("ai_overview", ""),
        "source_news_items": douyin_record.get("ai_news_items", []),
        "source_full_transcript": douyin_record.get("ai_full_transcript", ""),
        "source_published_at": douyin_record.get("published_at", ""),
        "douyin_status": douyin.get("status", "missing"),
        "status": "ok" if evidence_ready else "empty",
        "topics": default_topics(),
    }
    if evidence_ready:
        try:
            output.update(call_ai(multi, douyin_record))
            output["ai_status"] = "ok"
        except Exception as exc:
            output.update({
                "status": "partial",
                "ai_status": "error",
                "error": str(exc)[:180],
                "topics": source_backed_topics(multi),
            })
    else:
        output["note"] = "\u8fd124\u5c0f\u65f6\u6682\u65e0\u53ef\u7528\u7684\u516c\u5f00\u8bc1\u636e"
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": output["status"], "source_status": output["source_status"], "source_count": output["source_count"], "evidence_count": output["evidence_count"], "updated_at": output["updated_at"], "topics": len(output["topics"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
