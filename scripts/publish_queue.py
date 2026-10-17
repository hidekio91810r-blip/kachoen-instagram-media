"""予約キュー(queue/*.json)のうち、投稿時刻を過ぎたものをInstagramに投稿する。GitHub Actionsから30分ごとに実行。

標準ライブラリのみ。トークンは環境変数 INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID から読む。出力しない。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://graph.instagram.com/v23.0"
ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
UID = os.environ["INSTAGRAM_USER_ID"]


def call(method, path, params=None):
    data = urllib.parse.urlencode(params).encode() if params else None
    req = urllib.request.Request(f"{API}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Instagram APIエラー {e.code}: {e.read().decode()[:500]}")


def wait_ready(container_id):
    for _ in range(30):
        st = call("GET", f"{container_id}?fields=status_code").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            sys.exit(f"コンテナが失敗しました: {st}")
        time.sleep(5)
    sys.exit("コンテナの準備がタイムアウトしました")


def image_ok(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=20).status == 200
    except urllib.error.URLError:
        return False


def publish(entry):
    urls = entry["images"]
    if not all(image_ok(u) for u in urls):
        sys.exit(f"{entry['id']}: 画像がまだ公開されていません。次回に再試行します。")
    if len(urls) == 1:
        c = call("POST", f"{UID}/media", {"image_url": urls[0], "caption": entry["caption"]})["id"]
    else:
        kids = []
        for u in urls:
            kid = call("POST", f"{UID}/media", {"image_url": u, "is_carousel_item": "true"})["id"]
            wait_ready(kid)
            kids.append(kid)
        c = call("POST", f"{UID}/media", {
            "media_type": "CAROUSEL", "children": ",".join(kids), "caption": entry["caption"]})["id"]
    wait_ready(c)
    return call("POST", f"{UID}/media_publish", {"creation_id": c})["id"]


def main():
    now = datetime.now(timezone.utc)
    due = 0
    for path in sorted((ROOT / "queue").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry.get("status") != "scheduled":
            continue
        if datetime.fromisoformat(entry["scheduled_at"]) > now:
            continue
        due += 1
        media_id = publish(entry)
        entry.update(status="published", instagram_media_id=media_id,
                     published_at=now.isoformat(timespec="seconds"))
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        print("投稿しました:", entry["id"], media_id)
    if not due:
        print("投稿の対象はありません")


if __name__ == "__main__":
    main()
