"""
네이버 뉴스 수집기 (1단계)
결과: naver_news_raw.csv
"""

import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# ── 설정값 ──────────────────────────────────────────────
KEYWORDS = [
    "외식업 정책",
    "배달앱 수수료",
    "배달 포장 주문",
    "퀵커머스",
    "식당 예약",
    "웨이팅 노쇼",
    "키오스크 테이블오더",
    "프랜차이즈",
    "POS 솔루션",
    "외식업 경기",
    "음식점 폐업",
    "배달 시장",
    "외식 물가",
    "카페 시장",
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
    "AI 에이전트 예약",
    "AI 에이전트 주문",
]

DATE_FROM = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
DATE_TO   = datetime.today().strftime("%Y-%m-%d")

DISPLAY   = 100   # 키워드당 최대 수집 건수 (최대 100)
OUTPUT    = "naver_news_raw.csv"
# ────────────────────────────────────────────────────────

CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

if not CLIENT_ID or not CLIENT_SECRET:
    raise EnvironmentError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정하세요.")


def search_news(keyword: str, display: int = 100) -> list[dict]:
    """네이버 뉴스 검색 API 호출 → 기사 리스트 반환"""
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


def in_date_range(date_str: str, date_from: str, date_to: str) -> bool:
    return date_from <= date_str <= date_to


def main():
    date_from = DATE_FROM
    date_to   = DATE_TO
    print(f"수집 기간: {date_from} ~ {date_to}")
    print(f"키워드 수: {len(KEYWORDS)}")

    all_rows = []
    for kw in KEYWORDS:
        print(f"  검색 중: [{kw}]", end=" ", flush=True)
        try:
            items = search_news(kw, display=DISPLAY)
        except Exception as e:
            print(f"오류 → {e}")
            continue

        kept = 0
        for item in items:
            pub = parse_date(item.get("pubDate", ""))
            if not in_date_range(pub, date_from, date_to):
                continue
            all_rows.append({
                "keyword":       kw,
                "title":         item.get("title", "").replace("<b>", "").replace("</b>", ""),
                "description":   item.get("description", "").replace("<b>", "").replace("</b>", ""),
                "originallink":  item.get("originallink", ""),
                "link":          item.get("link", ""),
                "pubDate":       pub,
            })
            kept += 1
        print(f"{kept}건")
        time.sleep(0.1)

    if not all_rows:
        print("수집된 기사가 없습니다.")
        return

    df = pd.DataFrame(all_rows)
    df.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료 → {OUTPUT}  ({len(df)}행)")


if __name__ == "__main__":
    main()
