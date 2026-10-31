"""確認の Issue への院長のコメント(OK / NG)を youtube/videos.json に反映する。

誰のコメントを受け付けるかは youtube_approve.yml で OWNER に絞っている。
"""
import json
import os
import re
import urllib.request

DATA_PATH = "youtube/videos.json"
MAX_TITLE = 60
USAGE = (
    "読み取れませんでした。コメントの1行目を `OK`、`OK 新しい題名`、`NG` のどれかにしてください。"
    "テーマを変えるときは2行目に `テーマ 目のケア` のように書きます。"
)


def parse_comment(body, themes):
    """(動作, 題名, テーマ, エラー) を返す。動作は "ok" / "ng" / None"""
    lines = [l.strip() for l in body.strip().splitlines() if l.strip()]
    if not lines:
        return None, None, None, USAGE
    first = lines[0].replace("ＯＫ", "OK").replace("ＮＧ", "NG").replace("`", "")
    m = re.fullmatch(r"(?i)(ok|ng)(?:[\s:：]+(.*))?", first)
    if not m:
        return None, None, None, USAGE
    action = m.group(1).lower()
    title = (m.group(2) or "").strip()
    if action == "ng":
        return "ng", None, None, None
    if len(title) > MAX_TITLE:
        return None, None, None, f"題名は{MAX_TITLE}文字以内にしてください。"
    theme = None
    for line in lines[1:]:
        t = re.fullmatch(r"テーマ[\s:：]+(.+)", line.replace("`", ""))
        if t:
            theme = t.group(1).strip()
            if theme not in themes:
                return None, None, None, f"テーマは次から選んでください: {'、'.join(themes)}"
    return "ok", title or None, theme, None


def apply_comment(data, video_id, action, title, theme):
    item = data["pending"].pop(video_id)
    if action == "ng":
        data["excluded"].append(video_id)
        return "載せないことにしました。"
    final_title = title or item["title"]
    final_theme = theme or item["theme"]
    data["videos"].insert(0, {
        "id": video_id,
        "title": final_title,
        "theme": final_theme,
        "date": item["date"],
    })
    return f"載せました(数分で反映されます)。題名: {final_title} / テーマ: {final_theme}"


def github(method, path, payload=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        data=json.dumps(payload).encode() if payload else None,
        method=method,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read()


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    number = event["issue"]["number"]
    with open(DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)
    video_id = next((k for k, v in data["pending"].items() if v["issue"] == number), None)
    if video_id is None:
        print(f"Issue #{number} は確認待ちの動画ではありません")
        return
    action, title, theme, error = parse_comment(event["comment"]["body"], data["themes"])
    if error:
        github("POST", f"issues/{number}/comments", {"body": error})
        return
    message = apply_comment(data, video_id, action, title, theme)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    # 先に保存してから返事を書くため、結果の投稿はワークフローの push 後に行う
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
        f.write(f"YT_ISSUE={number}\nYT_MESSAGE={message}\n")


def reply():
    number = os.environ.get("YT_ISSUE")
    if not number:
        return
    github("POST", f"issues/{number}/comments", {"body": os.environ["YT_MESSAGE"]})
    github("PATCH", f"issues/{number}", {"state": "closed"})


if __name__ == "__main__":
    import sys
    reply() if "--reply" in sys.argv else main()
