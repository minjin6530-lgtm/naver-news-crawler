"""
네이버 뉴스 수집기 (1단계)
결과: naver_news_raw.csv
"""

import os
import csv
import time
import requests
from datetime import datetime, timedelta

# ── 설정값 ──────────────────────────────────────────────
KEYWORDS = [
    # 업종 키워드
    "외식업 정책",
    "배달앱 수수료",
    "배달 포장 주문",
    "퀵커머스",
    "식당 예약",
    "웨이팅 노쇼",
    "키오스크 테이블오더",
    "프랜차이즈",
    "POS 솔루션",
    # 경기/구조 키워드
    "외식업 경기",
    "음식점 폐업",
    "배달 시장",
    "외식 물가",
    "카페 시장",
    # 경쟁사명
    "배달의민족",
    "쿠팡이츠",
    "요기요",
    "캐치테이블",
    "테이블링",
    "티오더",
    "배민오더",
    "하이오더",
    "페이히어",
    "오케이포스",
    # 트렌드 키워드
    "AI 에이전트 예약",
    "AI 에이전트 주문",
]

DATE_FROM = datetime.today().strftime("%Y-%m-%d")
DATE_TO   = datetime.today().strftime("%Y-%m-%d")

DISPLAY = 100   # 키워드당 최대 수집 건수 (API 최대 100)
OUTPUT  = "naver_news_raw.csv"
# ────────────────────────────────────────────────────────

CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

if not CLIENT_ID or not CLIENT_SECRET:
    raise EnvironmentError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정하세요.")


def search_news(keyword: str, display: int = 100) -> list:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
    }
    results = []
    start = 1
    per_page = min(display, 100)

    while len(results) < display:
        params = {
            "query": keyword,
            "display": per_page,
            "start": start,
            "sort": "date",
        }
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        results.extend(items)
        if len(items) < per_page:
            break
        start += per_page
        time.sleep(0.2)

    return results[:display]


def parse_date(pub_date_str: str) -> str:
    """'Thu, 19 Jun 2025 14:30:00 +0900' → '2025-06-19'"""
    try:
        dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return pub_date_str


def clean_html(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")


def in_date_range(date_str: str, date_from: str, date_to: str) -> bool:
    return date_from <= date_str <= date_to


def main():
    print(f"수집 기간: {DATE_FROM} ~ {DATE_TO}")
    print(f"키워드 수: {len(KEYWORDS)}\n")

    fieldnames = ["keyword", "title", "description", "originallink", "link", "pubDate"]
    rows = []

    for kw in KEYWORDS:
        print(f"  [{kw}]", end=" ", flush=True)
        try:
            items = search_news(kw, display=DISPLAY)
        except Exception as e:
            print(f"오류 → {e}")
            continue

        kept = 0
        for item in items:
            pub = parse_date(item.get("pubDate", ""))
            if not in_date_range(pub, DATE_FROM, DATE_TO):
                continue
            rows.append({
                "keyword":      kw,
                "title":        clean_html(item.get("title", "")),
                "description":  clean_html(item.get("description", "")),
                "originallink": item.get("originallink", ""),
                "link":         item.get("link", ""),
                "pubDate":      pub,
            })
            kept += 1
        print(f"{kept}건")
        time.sleep(0.1)

    if not rows:
        print("\n수집된 기사가 없습니다.")
        return

    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n저장 완료 → {OUTPUT}  (총 {len(rows)}건)")


if __name__ == "__main__":
    main()
