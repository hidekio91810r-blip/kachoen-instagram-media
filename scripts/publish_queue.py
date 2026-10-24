"""予約キュー(queue/*.json)のうち、投稿時刻を過ぎたものをInstagramに投稿する。GitHub Actionsから30分ごとに実行。
キューに "gbp" があれば、同じ時刻にGoogleビジネスプロフィールにも投稿する。

標準ライブラリのみ。トークンは環境変数から読む。出力しない。
  Instagram: INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID
  Google:    GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN / GBP_ACCOUNT_ID / GBP_LOCATION_ID
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
GBP_API = "https://mybusiness.googleapis.com/v4"
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


def gbp_publish(g):
    env = {k: os.environ.get(k) for k in (
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "GBP_ACCOUNT_ID", "GBP_LOCATION_ID")}
    if not all(env.values()):
        raise RuntimeError("Googleの認証情報(シークレット)がありません")
    data = urllib.parse.urlencode({
        "client_id": env["GOOGLE_CLIENT_ID"], "client_secret": env["GOOGLE_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    token = json.loads(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30).read())["access_token"]
    body = {"languageCode": "ja", "topicType": "STANDARD", "summary": g["summary"],
            "callToAction": {"actionType": g["action_type"], "url": g["action_url"]},
            "media": [{"mediaFormat": "PHOTO", "sourceUrl": g["image_url"]}]}
    path = f"accounts/{env['GBP_ACCOUNT_ID']}/locations/{env['GBP_LOCATION_ID']}/localPosts"
    req = urllib.request.Request(f"{GBP_API}/{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read()).get("name", "")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ビジネスプロフィールのAPIエラー {e.code}: {e.read().decode()[:300]}")


def main():
    now = datetime.now(timezone.utc)
    due, failed = 0, False
    for path in sorted((ROOT / "queue").glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(entry["scheduled_at"]) > now:
            continue
        g = entry.get("gbp")
        if entry.get("status") == "scheduled":
            due += 1
            media_id = publish(entry)
            entry.update(status="published", instagram_media_id=media_id,
                         published_at=now.isoformat(timespec="seconds"))
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Instagramに投稿しました:", entry["id"], media_id)
        # ビジネスプロフィール(Instagramの投稿後。失敗したら次回に再試行。最大10回)
        if entry.get("status") == "published" and g and not g.get("published_at") and g.get("attempts", 0) < 10:
            due += 1
            try:
                g["post_name"] = gbp_publish(g)
                g["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                print("ビジネスプロフィールに投稿しました:", entry["id"])
            except Exception as e:  # Instagramの結果は残し、次回に再試行する
                g["attempts"] = g.get("attempts", 0) + 1
                g["last_error"] = str(e)[:300]
                print(f"ビジネスプロフィールへの投稿に失敗しました({g['attempts']}回目):", entry["id"], str(e)[:300])
                failed = True
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    if not due:
        print("投稿の対象はありません")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
