#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 行业速递 · 自动版 —— 每日播客生成器（GitHub Actions 里运行）

流程：读 feed.xml 最近 26 小时的条目 -> DeepSeek 写双人对谈稿（无 key 时用标题播报稿兜底）
-> edge-tts 双音色逐句合成 -> ffmpeg 拼接 -> episodes/ep-YYYYMMDD.mp3 + podcast.xml
订阅地址：https://<用户名>.github.io/ai-news-feed/podcast.xml
依赖：edge-tts（pip）、ffmpeg（系统）。DeepSeek key 从环境变量 DEEPSEEK_API_KEY 读。
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime, format_datetime
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
EP_DIR = os.path.join(BASE, "episodes")
SITE = os.environ.get("SITE_BASE", "https://emtion.github.io/ai-news-feed")
KEEP_EPISODES = 30
CST = timezone(timedelta(hours=8))

VOICE_A = "zh-CN-YunyangNeural"   # 男声，新闻播报腔
VOICE_B = "zh-CN-XiaoxiaoNeural"  # 女声


def recent_items(feed_path, hours=26, fallback_n=20):
    tree = ET.parse(feed_path)
    items = []
    cutoff = time.time() - hours * 3600
    for it in tree.getroot().find("channel").findall("item"):
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:
            ts = 0
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "desc": (it.findtext("description") or "").strip()[:200],
            "source": (it.findtext("source") or "").strip(),
            "ts": ts,
        })
    fresh = [i for i in items if i["ts"] >= cutoff]
    return fresh if len(fresh) >= 5 else items[:fallback_n]


def script_via_deepseek(items):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return None
    news = "\n".join(f"- [{i['source']}] {i['title']}。{i['desc']}" for i in items[:25])
    prompt = (
        "你是播客编剧。把下面今天的 AI 行业新闻改写成一期 5 到 7 分钟的中文双人对谈播客稿。\n"
        "主持人：A 是男声，负责讲事实和背景；B 是女声，负责追问和总结意义。\n"
        "要求：口语化，不要念标题原文，要把新闻讲成故事；挑最重要的 5 到 7 条深讲，其余一句话带过；"
        "开头 A 先说一句「欢迎收听 AI 行业速递」并报今天日期；结尾 B 做一句总结并说下期见。"
        "不要括号里的舞台说明，不要 markdown。\n"
        "格式：每一行一句台词，以「A：」或「B：」开头，每句 20 到 60 字。\n\n今日新闻：\n" + news
    )
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        text = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
    lines = []
    for raw in text.splitlines():
        m = re.match(r"^\s*([AB])\s*[:：]\s*(.+)$", raw)
        if m:
            lines.append((m.group(1), m.group(2).strip()))
    return lines or None


def script_fallback(items, date_str):
    lines = [("A", f"欢迎收听 AI 行业速递，今天是{date_str}，先看今天最重要的几条 AI 新闻。")]
    for i, it in enumerate(items[:10]):
        who = "A" if i % 2 == 0 else "B"
        t = it["title"].split("|")[-1].strip()
        lines.append((who, f"{it['source']}消息：{t}。"))
    lines.append(("B", "以上就是今天的速递，更多内容见文字版订阅，我们下期见。"))
    return lines


def synth(lines, out_mp3):
    tmp = os.path.join(EP_DIR, "_parts")
    os.makedirs(tmp, exist_ok=True)
    parts = []
    for idx, (who, text) in enumerate(lines):
        voice = VOICE_A if who == "A" else VOICE_B
        p = os.path.join(tmp, f"{idx:03d}.mp3")
        subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice,
                        "--text", text, "--write-media", p],
                       check=True, capture_output=True, timeout=120)
        parts.append(p)
    silence = os.path.join(tmp, "sil.mp3")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", "0.35", silence],
                   check=True, capture_output=True)
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\nfile '{silence}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c:a", "libmp3lame", "-q:a", "4", out_mp3],
                   check=True, capture_output=True)
    for p in parts:
        os.remove(p)
    os.remove(silence)
    os.remove(lst)
    os.rmdir(tmp)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def write_podcast_xml(episodes):
    items = ""
    for ep in episodes:
        dt = datetime.strptime(ep["date"], "%Y%m%d").replace(tzinfo=CST)
        url = f"{SITE}/episodes/{ep['file']}"
        items += f"""  <item>
    <title>{esc(ep['title'])}</title>
    <description>{esc(ep['desc'])}</description>
    <link>{SITE}/</link>
    <guid isPermaLink="false">ep-{ep['date']}</guid>
    <pubDate>{format_datetime(dt)}</pubDate>
    <enclosure url="{url}" length="{ep['size']}" type="audio/mpeg"/>
  </item>
"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
<channel>
  <title>AI 行业速递 · 自动版</title>
  <link>{SITE}/</link>
  <description>每天自动生成的 AI 行业新闻播客：双人对谈，5 到 7 分钟讲完今天最重要的 AI 动态。文字版见同仓库 feed.xml。</description>
  <language>zh-cn</language>
  <itunes:author>Emtion</itunes:author>
  <itunes:category text="Technology"/>
{items}</channel>
</rss>
"""
    with open(os.path.join(BASE, "podcast.xml"), "w", encoding="utf-8") as f:
        f.write(xml)


def main():
    os.makedirs(EP_DIR, exist_ok=True)
    today = datetime.now(CST)
    date_key = today.strftime("%Y%m%d")
    date_str = f"{today.year}年{today.month}月{today.day}日"
    items = recent_items(os.path.join(BASE, "feed.xml"))
    if not items:
        print("no items, abort")
        return
    lines = script_via_deepseek(items) or script_fallback(items, date_str)
    print(f"script lines: {len(lines)}")
    fname = f"ep-{date_key}.mp3"
    out = os.path.join(EP_DIR, fname)
    synth(lines, out)
    print("wrote", fname, os.path.getsize(out), "bytes")

    manifest_path = os.path.join(EP_DIR, "episodes.json")
    manifest = {}
    if os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path, encoding="utf-8"))
    top = items[0]["title"].split("|")[-1].strip()[:40] if items else ""
    manifest[date_key] = {
        "date": date_key, "file": fname,
        "title": f"{today.month}月{today.day}日速递：{top}",
        "desc": "今日要点：" + "；".join(i["title"].split("|")[-1].strip()[:30] for i in items[:5]),
        "size": os.path.getsize(out),
    }
    # 只保留最近 KEEP_EPISODES 期，删掉更旧的音频
    keys = sorted(manifest.keys(), reverse=True)
    for old in keys[KEEP_EPISODES:]:
        p = os.path.join(EP_DIR, manifest[old]["file"])
        if os.path.exists(p):
            os.remove(p)
        del manifest[old]
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_podcast_xml([manifest[k] for k in sorted(manifest.keys(), reverse=True)])
    print("podcast.xml updated,", len(manifest), "episodes")


if __name__ == "__main__":
    main()
