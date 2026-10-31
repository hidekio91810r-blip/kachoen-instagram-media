"""YouTube の新しい動画を見つけて、掲載の確認を Issue で院長に依頼する。

youtube/videos.json に無い動画だけが対象。ホームページに載るのは、
院長が Issue に OK とコメントしたあと(youtube_approve.py)。
"""
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

CHANNEL_ID = "UCHLfoFl0lMdyW4uYnskO2oA"
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=" + CHANNEL_ID
DATA_PATH = "youtube/videos.json"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}
# 題名案で院長に見直してもらう言葉(医療広告の観点)
FLAG_WORDS = [
    "暴露", "絶対", "最強", "最高", "究極", "完全", "完璧", "徹底", "半額", "大損", "損", "失明", "危機",
    "警告", "驚愕", "残酷", "後悔", "失敗", "ヤバい", "真実", "治る", "視力回復", "99%", "放置", "正解",
]
THEME_RULES = [
    ("目のケア", r"目薬|食べ物|ドライアイ|ケア"),
    ("多焦点眼内レンズ", r"多焦点|オデッセイ|ピュアシー|PureSee|シナジー|パンオプティクス"),
    ("ICL・IPCL", r"ICL|IPCL|レーシック"),
    ("白内障手術", r"白内障|眼内レンズ|単焦点"),
]
DEFAULT_THEME = "目の病気"


def fetch_feed():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read()
        except OSError as e:
            print(f"取得に失敗({attempt + 1}回目): {e}")
            time.sleep(30)
    sys.exit("YouTube のフィードを取得できませんでした")


def parse_feed(xml_bytes):
    videos = []
    for entry in ET.fromstring(xml_bytes).findall("a:entry", NS):
        link = entry.find("a:link", NS).get("href", "")
        videos.append({
            "id": entry.find("yt:videoId", NS).text,
            "title": entry.find("a:title", NS).text or "",
            "date": entry.find("a:published", NS).text[:10],
            "short": "/shorts/" in link,
        })
    return videos


def draft_title(title):
    t = re.sub(r"【[^】]*】", " ", title)
    t = re.sub(r"^[^【】]*】", " ", t)
    return re.sub(r"\s+", " ", t).strip() or title


def guess_theme(title):
    for theme, pattern in THEME_RULES:
        if re.search(pattern, title, re.I):
            return theme
    return DEFAULT_THEME


def issue_body(video, draft, theme, themes, owner):
    flags = [w for w in FLAG_WORDS if w in video["title"]]
    lines = [
        f"@{owner} 新しい動画があります。ホームページの YouTube ページに載せるか、コメントで教えてください。",
        "",
        f"![サムネイル](https://i.ytimg.com/vi/{video['id']}/hqdefault.jpg)",
        "",
        f"- 動画: https://www.youtube.com/watch?v={video['id']}",
        f"- YouTube の題名: {video['title']}",
        f"- ホームページの題名(案): **{draft}**",
        f"- テーマ(案): **{theme}**",
        f"- 投稿日: {video['date']}",
    ]
    if video["short"]:
        lines.append("- 種類: ショート動画")
    if flags:
        lines += ["", f"⚠️ 題名の見直し候補: {'、'.join(flags)}(案に残っていれば直してください)"]
    lines += [
        "",
        "サムネイルは YouTube のものがそのまま載ります。",
        "",
        "## 返事のしかた(コメントの1行目)",
        "- `OK` … 案のまま載せる",
        "- `OK 新しい題名` … 題名を変えて載せる",
        "- `NG` … 載せない",
        "",
        f"テーマを変えるときは2行目に `テーマ 目のケア` のように書きます。テーマ: {'、'.join(themes)}",
    ]
    return "\n".join(lines)


def create_issue(repo, token, title, body):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)["number"]


def main():
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    known = {v["id"] for v in data["videos"]} | set(data["excluded"]) | set(data["pending"])
    new = [v for v in parse_feed(fetch_feed()) if v["id"] not in known]
    print(f"新しい動画: {len(new)}本")
    for video in reversed(new):
        draft = draft_title(video["title"])
        theme = guess_theme(video["title"])
        number = create_issue(
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GITHUB_TOKEN"],
            f"【YouTube確認】{draft}",
            issue_body(video, draft, theme, data["themes"], os.environ["GITHUB_REPOSITORY_OWNER"]),
        )
        data["pending"][video["id"]] = {
            "issue": number,
            "title": draft,
            "theme": theme,
            "date": video["date"],
        }
        print(f"Issue #{number}: {video['id']}")
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
