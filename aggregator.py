# -*- coding: utf-8 -*-
"""
AI 新闻聚合器：抓取订阅源（RSS/Atom + 网页列表抓取），生成标准 RSS 2.0 feed.xml。
纯 Python 标准库，无第三方依赖。由 GitHub Actions 定时运行，state.json 保存已见文章的首见时间。
改订阅源：直接改下面 SOURCES 列表（一行一个），保存后下一次运行生效。
"""
import json, os, re, sys, time, html
import urllib.request, urllib.error
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime, format_datetime
from datetime import datetime, timezone

# ---------------- 配置 ----------------
FEED_TITLE = "AI 新闻聚合"
FEED_LINK = "https://aiindaily.com/"
FEED_DESC = "AI 行业新闻聚合：发布日志、日报聚合、官方一手源、工具与项目发现、中文媒体。"
MAX_ITEMS = 100          # feed.xml 里最多保留多少条
STATE_KEEP = 300         # state.json 里最多记住多少条
FEED_CAP = 40            # 每个 RSS 源单次最多取多少条
PAGE_CAP = 30            # 每个网页源单次最多取多少条
TIMEOUT = 20

# (名称, 地址) —— kind=feed 走 RSS/Atom 解析；kind=page 走网页列表抓取
SOURCES = [
    # 发布日志 · 英文最快
    ("The Model Gap", "feed", "https://themodelgap.com/feed.xml"),
    ("CloudQuell 发布日志", "page", "https://www.cloudquell.com/blog/new-ai-models/"),
    ("Artificial Analysis 智力指数榜", "page", "https://artificialanalysis.ai/articles"),
    ("TechCrunch AI", "feed", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "feed", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("WIRED AI", "feed", "https://www.wired.com/feed/tag/ai/latest/rss"),
    ("Ars Technica", "feed", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Hacker News 头版", "feed", "https://hnrss.org/frontpage"),
    # 日报聚合 · 中文
    ("AI 日报 · AI225", "feed", "https://daily.ai225.com/rss.xml"),
    ("艾媒网", "page", "https://www.iimedia.cn/"),
    # 一手源 · 官方博客 / X
    ("OpenAI News", "feed", "https://openai.com/news/rss.xml"),
    ("Anthropic Newsroom", "page", "https://www.anthropic.com/news"),
    ("Google DeepMind", "feed", "https://deepmind.google/blog/rss.xml"),
    ("Google AI 博客", "feed", "https://blog.google/technology/ai/rss/"),
    ("DeepSeek 更新日志", "page", "https://api-docs.deepseek.com/updates"),
    ("Meta AI 博客", "page", "https://ai.meta.com/blog/"),
    ("Hugging Face 博客", "feed", "https://huggingface.co/blog/feed.xml"),
    # 工具与项目发现
    ("Product Hunt", "feed", "https://www.producthunt.com/feed"),
    ("Hugging Face Trending", "page", "https://huggingface.co/models?sort=trending"),
    ("GitHub Trending", "page", "https://github.com/trending"),
    # 中文媒体
    ("量子位", "feed", "https://www.qbitai.com/feed"),
    ("雷峰网", "feed", "https://www.leiphone.com/feed"),
    # 以下 5 个源为前端渲染/公众号发布，静态抓取拿不到文章，默认停用；
    # 找到可用镜像/RSS 后把行首的 # 去掉即可启用：
    # ("掘金 AI 日报", "page", "https://juejin.cn/search?query=AI%E6%97%A5%E6%8A%A5"),
    # ("千问 Qwen 官方博客", "page", "https://qwen.ai/research"),
    # ("豆包 · Seed 官方博客", "page", "https://seed.bytedance.com/zh/blog"),
    # ("机器之心", "page", "https://www.jiqizhixin.com/"),
    # ("新智元（公众号）", "page", "https://aiera.com.cn/"),
]

# 噪音过滤：综合类来源（非 AI 专属频道）只收标题/摘要命中 AI 关键词的文章；
# AI 专属源（官方博客、发布日志、AI 分类频道）和榜单型源（GitHub/HF Trending）不过滤。
FILTER_SOURCES = {"艾媒网", "Hacker News 头版", "Product Hunt", "Ars Technica"}
AI_KEYWORDS = ("人工智能", "大模型", "机器学习", "深度学习", "神经网络", "智能体",
               "llm", "gpt", "claude", "gemini", "deepseek", "openai", "anthropic",
               "qwen", "千问", "豆包", "文心", "混元", "aigc", "生成式", "多模态",
               "具身", "机器人", "算力", "gpu", "agent", "chatbot", "语言模型")

def ai_related(text):
    t = (text or "").lower()
    if re.search(r"(?<![a-z])ai(?![a-z])", t):  # 独立的 ai 一词，避免误伤 said/daily 等
        return True
    return any(k in t for k in AI_KEYWORDS)

UA_FULL = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
UA_BARE = "Mozilla/5.0"

def fetch(url):
    """先用完整 UA，遇 400/403 用极简 UA 重试一次（Meta 等站点会拒绝完整 UA）。"""
    last = None
    for ua in (UA_FULL, UA_BARE):
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (400, 403):
                raise
    raise last

def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_feed(data):
    items = []
    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    if root.tag.endswith("feed"):  # Atom
        for e in root.findall("atom:entry", ns):
            t = e.findtext("atom:title", "", ns).strip()
            link = ""
            for l in e.findall("atom:link", ns):
                if l.get("rel") in (None, "alternate"):
                    link = l.get("href", "")
                    break
            d = parse_date(e.findtext("atom:published", None, ns) or e.findtext("atom:updated", None, ns))
            desc = (e.findtext("atom:summary", "", ns) or "").strip()
            if t and link:
                items.append({"title": html.unescape(t), "link": link, "date": d, "desc": html.unescape(re.sub("<[^>]+>", "", desc))[:300]})
    else:  # RSS 2.0
        for it in root.iter("item"):
            t = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            d = parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date"))
            desc = (it.findtext("description") or "").strip()
            if t and link:
                items.append({"title": html.unescape(t), "link": link, "date": d, "desc": html.unescape(re.sub("<[^>]+>", "", desc))[:300]})
    return items[:FEED_CAP]

SKIP_SUBSTR = ("/tag/", "/tags/", "/category/", "/author/", "/search", "/login", "/signin",
               "/signup", "/register", "/about", "/contact", "/privacy", "/terms",
               "/compare/", "/page/", "/feed", ".xml", "javascript:", "mailto:", "#")

class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._href = None
        self._text = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []

def scrape_page(url):
    data = fetch(url)
    text = data.decode("utf-8", errors="replace")
    p = AnchorParser()
    p.feed(text)
    base_host = urlparse(url).netloc
    seen, out = set(), []
    for href, title in p.anchors:
        if not href:
            continue
        full = urljoin(url, href)
        u = urlparse(full)
        if u.scheme not in ("http", "https") or u.netloc != base_host:
            continue
        low = full.lower()
        if any(s in low for s in SKIP_SUBSTR):
            continue
        # GitHub / HF 两段式路径（owner/repo、org/model）用路径当标题
        segs = [s for s in u.path.split("/") if s]
        if base_host in ("github.com", "huggingface.co") and len(segs) == 2 and not title:
            title = segs[0] + " / " + segs[1]
        if len(title) < 14:  # 标题太短的多半是导航
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append({"title": title, "link": full, "date": None, "desc": ""})
        if len(out) >= PAGE_CAP:
            break
    return out

def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    state_path = os.path.join(here, "state.json")
    feed_path = os.path.join(here, "feed.xml")
    state = load_state(state_path)  # link -> {title, source, ts}
    # 清理历史噪音：过滤源里已入库的非 AI 文章一并剔除，下一次生成即干净
    for link in [l for l, v in state.items()
                 if v.get("source") in FILTER_SOURCES and not ai_related(v.get("title", ""))]:
        del state[link]
    now = time.time()
    total_new = 0
    for name, kind, url in SOURCES:
        try:
            if kind == "feed":
                items = parse_feed(fetch(url))
            else:
                items = scrape_page(url)
        except Exception as e:
            print(f"[skip] {name}: {e}")
            continue
        if name in FILTER_SOURCES:
            items = [it for it in items if ai_related(it["title"] + " " + it.get("desc", ""))]
        new = 0
        for it in items:
            link = it["link"]
            if link in state:
                continue
            ts = it["date"].timestamp() if it.get("date") else now
            state[link] = {"title": it["title"], "source": name, "ts": ts, "desc": it.get("desc", "")}
            new += 1
        total_new += new
        print(f"[ok] {name}: {len(items)} fetched, {new} new")
    # 只保留最新 STATE_KEEP 条
    ordered = sorted(state.items(), key=lambda kv: kv[1]["ts"], reverse=True)
    state = dict(ordered[:STATE_KEEP])
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    # 生成 feed.xml
    from xml.sax.saxutils import escape
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', '<channel>',
             f"  <title>{escape(FEED_TITLE)}</title>", f"  <link>{escape(FEED_LINK)}</link>",
             f"  <description>{escape(FEED_DESC)}</description>", "  <language>zh-cn</language>",
             f"  <lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>"]
    for link, it in ordered[:MAX_ITEMS]:
        lines.append("  <item>")
        lines.append(f"    <title>{escape(it['title'])}</title>")
        lines.append(f"    <link>{escape(link)}</link>")
        lines.append(f'    <guid isPermaLink="true">{escape(link)}</guid>')
        lines.append(f"    <pubDate>{format_datetime(datetime.fromtimestamp(it['ts'], timezone.utc))}</pubDate>")
        lines.append(f"    <source>{escape(it['source'])}</source>")
        if it.get("desc"):
            lines.append(f"    <description>{escape(it['desc'])}</description>")
        lines.append("  </item>")
    lines += ["</channel>", "</rss>"]
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"done: {total_new} new, feed.xml has {min(len(ordered), MAX_ITEMS)} items")

if __name__ == "__main__":
    main()
