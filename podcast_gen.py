#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 行业速递 · 自动版 —— 每日播客生成器（GitHub Actions 里运行）

流程：读 feed.xml 最近 26 小时的条目 -> 大模型写双人对谈稿（优先 GitHub Models 免费额度，其次 DeepSeek；都不可用时用标题播报稿兜底）
-> edge-tts 双音色逐句合成 -> ffmpeg 拼接 -> episodes/ep-YYYYMMDD.mp3 + podcast.xml
订阅地址：https://<用户名>.github.io/ai-news-feed/podcast.xml
依赖：edge-tts（pip）。MP3 拼接为纯字节合并，不需要 ffmpeg。DeepSeek key 从环境变量 DEEPSEEK_API_KEY 读。
"""
import base64
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

VOICE_A = "zh-CN-YunjianNeural"   # 男声，成熟稳重（云健，edge-tts 名录已核实）
VOICE_B = "zh-CN-XiaoxiaoNeural"  # 女声（晓晓，已验证可用；晓萌不在 edge-tts 目录里，整轨静音）

# 0.4 秒静音片段（24kHz/48kbps/单声道，与 edge-tts 输出同规格），作句间间隔与失败占位
SILENCE_B64 = (
    "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjYyLjEyLjEwMgAAAAAAAAAAAAAA//OEwAAAAAAAAAAA"
    "AEluZm8AAAAPAAAAEwAAC3AAHR0dHR0pKSkpKTY2NjY2Q0NDQ0NDT09PT09cXFxcXGhoaGhodXV1"
    "dXV1goKCgoKOjo6Ojpubm5ubp6enp6entLS0tLTBwcHBwc3Nzc3N2tra2tra5ubm5ubz8/Pz8///"
    "////AAAAAExhdmM2Mi4yOAAAAAAAAAAAAAAAACQDAAAAAAAAAAtwBmwvuQAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAA//NkxAAAAANIAAAAAExBTUVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVV"
    "VVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVV"
    "VVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAA"
    "AFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANI"
    "AAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwA"
    "AANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//Nk"
    "xHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4x"
    "MDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1F"
    "My4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVMQU1FMy4xMDBVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//NkxHwAAANIAAAAAFVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV"
    "VVVVVVVVVVVV"
)
SILENCE_MP3 = base64.b64decode(SILENCE_B64)


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
    def interleave(pool, limit):
        """按来源轮转交错取条目，保证写稿素材各源平均，不被单个源刷屏。"""
        by = {}
        for i in pool:
            by.setdefault(i["source"], []).append(i)
        out = []
        while len(out) < limit:
            progressed = False
            for s in by:
                if by[s] and len(out) < limit:
                    out.append(by[s].pop(0))
                    progressed = True
            if not progressed:
                break
        return out
    fresh = [i for i in items if i["ts"] >= cutoff]
    return interleave(fresh, 25) if len(fresh) >= 5 else interleave(items, fallback_n)


def _chat_completion(base_url, token, model, prompt):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url, data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def script_via_llm(items):
    """按顺序尝试各写稿模型：GitHub Models（免费）-> DeepSeek -> 都不行返回 None（走标题播报稿）。"""
    news = "\n".join(f"- [{i['source']}] {i['title']}。{i['desc']}" for i in items[:25])
    prompt = (
        "你是播客编剧。把下面今天的 AI 行业新闻改写成一期 5 到 7 分钟的中文双人对谈播客稿。\n"
        "主持人：男，负责讲事实和背景；女，负责追问和总结意义。\n"
        "要求：口语化，不要念标题原文，要把新闻讲成故事；挑最重要的 5 到 7 条深讲，其余一句话带过；"
        "开头男先说一句「欢迎收听 AI 行业速递」并报今天日期；结尾女做一句总结并说下期见。"
        "不要括号里的舞台说明，不要 markdown。\n"
        "格式：每一行一句台词，以「男：」或「女：」开头，每句 20 到 60 字。\n\n今日新闻：\n" + news
    )
    providers = []
    gh_token = os.environ.get("GH_MODELS_TOKEN", "").strip()
    if gh_token:
        providers.append(("GitHub Models", "https://models.github.ai/inference/chat/completions",
                          gh_token, os.environ.get("PODCAST_LLM_MODEL", "deepseek/DeepSeek-V3-0324")))
    ds_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if ds_key:
        providers.append(("DeepSeek", "https://api.deepseek.com/chat/completions", ds_key, "deepseek-chat"))
    for name, url, token, model in providers:
        try:
            text = _chat_completion(url, token, model, prompt)
            lines = []
            for raw in text.splitlines():
                m = re.match(r"^\s*([AB男女])\s*[:：]\s*(.+)$", raw)
                if m:
                    who = {"A": "男", "B": "女"}.get(m.group(1), m.group(1))  # 兼容模型偶尔仍写 A/B
                    lines.append((who, m.group(2).strip()))
            if lines:
                print(f"script by {name} ({model}): {len(lines)} lines")
                return lines
            print(f"[warn] {name} 返回内容没有可解析的台词，换下一个")
        except Exception as e:
            print(f"[warn] {name} 写稿失败，换下一个：{e}")
    return None


def script_fallback(items, date_str):
    lines = [("男", f"欢迎收听 AI 行业速递，今天是{date_str}，先看今天最重要的几条 AI 新闻。")]
    for i, it in enumerate(items[:10]):
        who = "男" if i % 2 == 0 else "女"
        t = it["title"].split("|")[-1].strip()
        lines.append((who, f"{it['source']}消息：{t}。"))
    lines.append(("女", "以上就是今天的速递，更多内容见文字版订阅，我们下期见。"))
    return lines


def synth(lines, out_mp3):
    tmp = os.path.join(EP_DIR, "_parts")
    os.makedirs(tmp, exist_ok=True)
    chunks = []
    for idx, (who, text) in enumerate(lines):
        voice = VOICE_A if who == "男" else VOICE_B
        p = os.path.join(tmp, f"{idx:03d}.mp3")
        data, last_err = None, None
        for attempt in range(3):  # 单句失败最多重试 3 次
            try:
                subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice,
                                "--text", text, "--write-media", p],
                               check=True, capture_output=True, timeout=120)
                data = open(p, "rb").read()
                break
            except Exception as e:
                last_err = e
                print(f"[warn] 第 {idx + 1} 句合成失败（第 {attempt + 1} 次）：{e}")
                time.sleep(3)
        if data is None:  # 半静音的节目比不发更糟：整期取消，日志里写明是哪个音色
            raise RuntimeError(f"第 {idx + 1} 句合成失败（音色 {voice}），已取消发布：{last_err}")
        chunks.append(data)
        chunks.append(SILENCE_MP3)
        if os.path.exists(p):
            os.remove(p)
    with open(out_mp3, "wb") as f:
        f.write(b"".join(chunks))  # MP3 帧可直接字节拼接，主流播放器均可播
    os.rmdir(tmp)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def write_podcast_xml(episodes):
    items = ""
    for ep in episodes:
        if ep.get("ts"):
            dt = datetime.fromtimestamp(ep["ts"], CST)
        else:
            dt = datetime.strptime(ep["date"], "%Y%m%d").replace(tzinfo=CST)
        url = f"{SITE}/episodes/{ep['file']}"
        items += f"""  <item>
    <title>{esc(ep['title'])}</title>
    <description>{esc(ep['desc'] + (("\n\n【本期文字稿】\n" + ep["script"]) if ep.get("script") else ""))}</description>
    <link>{SITE}/</link>
    <guid isPermaLink="false">{ep['file'].replace('.mp3', '')}</guid>
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
    lines = script_via_llm(items) or script_fallback(items, date_str)
    print(f"script lines: {len(lines)}")

    manifest_path = os.path.join(EP_DIR, "episodes.json")
    manifest = {}
    if os.path.exists(manifest_path):
        manifest = json.load(open(manifest_path, encoding="utf-8"))
    for v in manifest.values():  # 老条目补 ts（按日期零点），供排序与发布时间用
        if not v.get("ts"):
            v["ts"] = int(datetime.strptime(v["date"], "%Y%m%d").replace(tzinfo=CST).timestamp())
    # 同一天重复运行不覆盖旧期：已有当天节目时依次用 -2、-3 后缀另存一期
    stem, seq = f"ep-{date_key}", 1
    while stem in manifest or os.path.exists(os.path.join(EP_DIR, stem + ".mp3")):
        seq += 1
        stem = f"ep-{date_key}-{seq}"
    fname = stem + ".mp3"
    out = os.path.join(EP_DIR, fname)
    synth(lines, out)
    print("wrote", fname, os.path.getsize(out), "bytes")
    script_text = "\n".join(f"{who}：{text}" for who, text in lines)
    with open(os.path.join(EP_DIR, stem + ".txt"), "w", encoding="utf-8") as f:
        f.write(f"AI 行业速递 · 自动版 {date_str}\n\n{script_text}\n")

    top = items[0]["title"].split("|")[-1].strip()[:40] if items else ""
    title = f"{today.month}月{today.day}日速递：{top}"
    if seq >= 2:
        title += f"（第{seq}版）"
    manifest[stem] = {
        "date": date_key, "file": fname, "ts": int(time.time()), "seq": seq,
        "title": title,
        "desc": "今日要点：" + "；".join(i["title"].split("|")[-1].strip()[:30] for i in items[:5]),
        "size": os.path.getsize(out),
        "script": script_text,
    }
    # 只保留最近 KEEP_EPISODES 期（按生成时间），删掉更旧的音频
    keys = sorted(manifest.keys(), key=lambda k: -manifest[k].get("ts", 0))
    for old in keys[KEEP_EPISODES:]:
        p = os.path.join(EP_DIR, manifest[old]["file"])
        if os.path.exists(p):
            os.remove(p)
        t = os.path.join(EP_DIR, manifest[old]["file"].replace(".mp3", ".txt"))
        if os.path.exists(t):
            os.remove(t)
        del manifest[old]
    json.dump(manifest, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_podcast_xml([manifest[k] for k in sorted(manifest.keys(), key=lambda k: -manifest[k].get("ts", 0))])
    print("podcast.xml updated,", len(manifest), "episodes")


if __name__ == "__main__":
    main()
