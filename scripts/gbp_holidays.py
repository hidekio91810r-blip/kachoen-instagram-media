"""祝日をGoogleビジネスプロフィールの特別営業時間に「休業」として登録する。GitHub Actionsから毎月実行。

- 今日から DAYS 日先までの祝日(振替休日を含む。jpholiday で判定)を対象にする
- 登録済みの日は触らない(既存の登録を読んでから足す。上書きで消さない)。
  祝日に診療する日は、先に特別営業時間に診療時間を登録しておけば、そのまま残る
- 何度動かしても同じ結果になる。新しい祝日が対象期間に入ったら、その分だけ足す

jpholiday 以外は標準ライブラリのみ。トークンは環境変数から読む。出力しない。
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN / GBP_LOCATION_ID
手元で試すとき: .env の値を環境変数に入れて --dry-run を付ける。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import jpholiday

API = "https://mybusinessbusinessinformation.googleapis.com/v1/locations"
DAYS = 400  # 約13か月先まで
JST = timezone(timedelta(hours=9))


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    return json.loads(urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30).read())["access_token"]


def request(method, url, token, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"ビジネスプロフィールのAPIエラー {e.code}: {e.read().decode()[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = access_token()
    url = f"{API}/{os.environ['GBP_LOCATION_ID']}"
    periods = request("GET", f"{url}?readMask=specialHours", token).get("specialHours", {}).get("specialHourPeriods", [])
    have = {date(p["startDate"]["year"], p["startDate"]["month"], p["startDate"]["day"]) for p in periods}

    today = datetime.now(JST).date()
    new = [(d, n) for d, n in jpholiday.between(today, today + timedelta(days=DAYS)) if d not in have]
    if not new:
        print("足す祝日はありません。")
        return
    for d, n in new:
        print(f"休業を追加: {d} {n}")
    if args.dry_run:
        print("[dry-run] 登録はしていません。")
        return

    periods += [{"startDate": {"year": d.year, "month": d.month, "day": d.day}, "closed": True} for d, _ in new]
    request("PATCH", f"{url}?updateMask=specialHours", token, {"specialHours": {"specialHourPeriods": periods}})
    print(f"{len(new)}日分を登録しました。")


if __name__ == "__main__":
    main()
