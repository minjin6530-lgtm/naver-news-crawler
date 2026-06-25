"""
API 연결 확인용 임시 스크립트 (pandas 없이 csv 표준 모듈 사용)
테스트 후 삭제해도 됩니다.
"""

import os
import csv
import time
import requests
from datetime import datetime, timedelta

KEYWORD   = "테스트"
DATE_FROM = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
DATE_TO   = datetime.today().strftime("%Y-%m-%d")
OUTPUT    = "naver_news_raw.csv"

CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

if not CLIENT_ID or not CLIENT_SECRET:
    raise EnvironmentError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정하세요.")

print(f"CLIENT_ID 확인: {CLIENT_ID[:4]}****")
print(f"수집 기간: {DATE_FROM} ~ {DATE_TO}")
print(f"키워드: [{KEYWORD}]")


def search_news(keyword: str, display: int = 10) -> list:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
    }
    params = {"query": keyword, "display": display, "start": 1, "sort": "date"}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("items", [])


def parse_date(pub_date_str: str) -> str:
    try:
        dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return pub_date_str


print("\nAPI 호출 중...", end=" ", flush=True)
items = search_news(KEYWORD, display=10)
print(f"응답 {len(items)}건")

rows = []
for item in items:
    pub = parse_date(item.get("pubDate", ""))
    if DATE_FROM <= pub <= DATE_TO:
        rows.append({
            "keyword":      KEYWORD,
            "title":        item.get("title", "").replace("<b>", "").replace("</b>", ""),
            "description":  item.get("description", "").replace("<b>", "").replace("</b>", ""),
            "originallink": item.get("originallink", ""),
            "link":         item.get("link", ""),
            "pubDate":      pub,
        })

print(f"기간 내 기사: {len(rows)}건")

if rows:
    fieldnames = ["keyword", "title", "description", "originallink", "link", "pubDate"]
    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n저장 완료 → {OUTPUT}  ({len(rows)}행)")
    print("\n[샘플 첫 번째 기사]")
    print(f"  제목: {rows[0]['title'][:60]}")
    print(f"  날짜: {rows[0]['pubDate']}")
else:
    print("\n최근 1일 기사가 없어 전체 응답 결과만 저장합니다.")
    fieldnames = ["keyword", "title", "description", "originallink", "link", "pubDate"]
    all_rows = [{
        "keyword":      KEYWORD,
        "title":        i.get("title", "").replace("<b>", "").replace("</b>", ""),
        "description":  i.get("description", "").replace("<b>", "").replace("</b>", ""),
        "originallink": i.get("originallink", ""),
        "link":         i.get("link", ""),
        "pubDate":      parse_date(i.get("pubDate", "")),
    } for i in items]
    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"저장 완료 → {OUTPUT}  ({len(all_rows)}행)")
