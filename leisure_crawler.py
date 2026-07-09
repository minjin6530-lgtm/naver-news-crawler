"""
네이버 뉴스 검색 API — 레저 업종 기사 수집 스크립트
수집 기간: 2026-07-01 ~ 2026-07-09

사용법:
    export NAVER_CLIENT_ID="..."
    export NAVER_CLIENT_SECRET="..."
    python leisure_crawler.py

출력: leisure_news_raw.csv (1차 수집 원본)
      leisure_news_final.xlsx (Claude Code가 요약/중요도 채운 최종 결과)
"""

import os, re, csv, time, html, json
import urllib.request, urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DATE_FROM = "2026-07-01"
DATE_TO   = "2026-07-09"

CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
API_URL       = "https://openapi.naver.com/v1/search/news.json"
OUTPUT_CSV    = "leisure_news_raw.csv"

# ── 1) 업종 키워드 (무조건 1회 이상 검색) ──────────────
# 2026-07-09: "관광정책/관광공사/체험 플랫폼/K-컬처 관광/워케이션"은 검색어가 너무 범용적이라
#   무관 기사(지자체 행정, 팝업스토어, 식품/자동차 홍보 등) 비중이 80~90%에 달해 수집 대상에서 제외.
INDUSTRY_KEYWORDS = [
    "액티비티 플랫폼",
    "골프장 예약",
    "스키장 예약",
    "테마파크 예약",
    "여행 AI 에이전트",
    "외국인 관광",
    "인바운드 관광",
    "키즈카페 폐업",
    "키즈카페 방문",
    "롯데월드 입장",
    "에버랜드 입장",
    "공간대여",
    "공간예약",
]

# ── 2) 경기/구조 키워드 (무조건 1회 이상 검색) ─────────
ECONOMY_KEYWORDS = [
    "여행업 매출",
    "여행업 실적",
    "관광업 매출",
    "관광업 실적",
    "해외여행 증감",
    "관광수지",
    "국내여행 선호",
    "방한 외국인",
    "유류할증료 해외여행",
]

# ── 3) 경쟁사 키워드 ────────────────────────────────────
COMPETITOR_KEYWORDS = [
    "쿠팡트래블",
    "야놀자",
    "마이리얼트립",
    "와그",
    "스페이스클라우드",
    "아워플레이스",
    "카카오골프예약",
    "카카오VX 골프",
    "엑스골프",          # xgolf
]

# ── 4) 메인 관심사 추가 키워드 ──────────────────────────
TREND_KEYWORDS = [
    "OTA 슈퍼앱",
    "여행 플랫폼 슈퍼앱",
    "인바운드 외국인 예약",
    "공간대여 예약 플랫폼",
    "SIT 여행",
    "FIT 여행",
    "패키지 여행 수요",
    "AI 여행 추천",
    "AI 에이전트 여행 예약",
]

# 검색 대상 전체 = 업종 + 경기/구조 + 경쟁사 + 트렌드
ALL_KEYWORDS = (
    INDUSTRY_KEYWORDS +
    ECONOMY_KEYWORDS +
    COMPETITOR_KEYWORDS +
    TREND_KEYWORDS
)

# ── 제외 키워드 (제목+설명에 포함 시 제외) ──────────────
EXCLUDE_KEYWORDS = [
    "여행지 추천",
    "항공권 할인",
    "항공사 실적",
    "항공 노선",
    "여행 에세이",
    "여가 장소 추천",
    "맛집",
    "숙소 추천",
    "호텔 추천",
    "여행 코스",
    # ── 범용 키워드(관광정책/관광공사/체험 플랫폼/공간예약/외국인 관광 등)가
    #    끌어오는 완전 무관 카테고리 노이즈 제거용 (2026-07-09 추가) ──
    "[인사]", "부고", "동정)", "인사)",
    "팝업스토어", "팝업 in", "플래그십 스토어", "그랜드 오픈",
    "사전계약", "신차", "그랜저", "출시 1년", "누적 판매", "판매량 돌파",
    "적극행정", "조직문화", "행복청", "합동 점검", "중량 미달",
    "교환사채", "경상수지", "반도체가 밀어올린",
    "장류축제", "포토]", "[포토",
    "채용", "공모전 접수",
    # ── 제외 원칙 (2026-07-09, 전 키워드 공통 적용) ──
    # 네이버 플레이스는 오프라인 장소를 검색·예약·주문하는 플랫폼이므로
    # "장소/업체/사업자" 관점과 무관한 아래 카테고리 기사는 제외
    "쿠폰", "특가", "기획전", "경품",                       # 할인/이벤트/프로모션
    "출시 기념", "기자간담회", "홍보대사",                    # 홍보성 보도자료
    "MOU", "업무협약",                                     # 특정 지역 한정 MOU/협약
    "제휴",                                                # 단일 기관 제휴
    "임직원", "사내 복지",                                  # 임직원/내부 서비스
    "취임", "수상", "표창", "인사 발령",                      # 단순 인사/수상
    "기부", "봉사", "장학금", "나눔",                        # 사회공헌/CSR
    "유튜브", "웹드라마", "콘텐츠 제작",                      # 유튜브/콘텐츠 협업
    "도서", "금리", "대출", "보험", "주식",                   # 비관련 카테고리
]

# ── 최신순 상한 (검색어가 넓어 결과가 많은 키워드는 최신 N건만 채택) ──
CAP_KEYWORDS = {"공간예약", "외국인 관광", "방한 외국인"}
CAP_N = 100

# ── 메인 관심사 (importance ★★★ 판단 기준 — Claude Code 참고용) ──
MAIN_INTERESTS = """
[레저 업종 메인 관심사 — importance ★★★ 기준]
1. 인바운드 관광 증감 (방한 외국인 규모, K-컬처 연계 레저 소비)
2. 여행 AI 에이전트 (해외 사례 포함, 예약/추천 자동화)
3. OTA 플랫폼 슈퍼앱 경쟁 (야놀자, 쿠팡트래블, 마이리얼트립 등)
4. 레저 트렌드 이동 (무엇을 하며 노는지, 대형 시설 경기)
5. 공간대여 시장 성장 및 예약 플랫폼 동향
6. 경쟁사의 '예약' 기능 관련 신규 서비스/제휴/전략
7. 해외여행 vs 국내여행 선호 변화 (유류할증료, 환율 영향)
8. 여행 수요 구조 변화: 패키지 → SIT/FIT 전환

[importance 기준]
★★★: 위 메인 관심사에 직접 해당, 경쟁사 구체 행동(신규 기능/제휴/실적), 제도 변화
★★ : 관광업 경기/구조 배경 트렌드, 간접 영향
★  : 키워드만 걸렸고 실질 무관 (노이즈)

[수집 우선순위]
- 경쟁사 기사: 예약 기능 관련 > 매출/실적 > 전략 분석 순
- 공간대여: 예약 플랫폼 신규 기능/성장 기사 우선
- 6월 피드백 반영: 공간대여 성장, SIT/FIT 수요 전환, 유류할증료·환율 영향 기사 적극 수집

[summary_korean 작성 방식]
- '플레이스', '우리 사업', '우리 회사' 표현 없이 기사 내용만 두 마디로
- description을 그대로 베끼지 말고 핵심 재구성
"""


# ──────────────────────────────────────────────
# 크롤링 함수
# ──────────────────────────────────────────────
def strip_tags(text):
    text = re.sub(r"</?b>", "", text)
    return html.unescape(text).strip()


def is_excluded(title, description):
    combined = f"{title} {description}"
    return any(kw in combined for kw in EXCLUDE_KEYWORDS)


def extract_source(original_link, link):
    url = original_link or link
    try:
        return url.split("//")[-1].split("/")[0].replace("www.", "")
    except:
        return ""


def fetch_keyword(keyword, date_from_dt, date_to_dt):
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정하세요.")

    results = []
    start = 1

    while start <= 1000:
        params = {
            "query": keyword,
            "display": 100,
            "start": start,
            "sort": "date",
        }
        url = API_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])
        if not items:
            break

        stop = False
        for item in items:
            pub_dt = parsedate_to_datetime(item["pubDate"]).replace(tzinfo=None)

            if pub_dt.date() > date_to_dt.date():
                continue
            if pub_dt.date() < date_from_dt.date():
                stop = True
                break

            title = strip_tags(item["title"])
            description = strip_tags(item["description"])

            if is_excluded(title, description):
                continue

            results.append({
                "search_keyword": keyword,
                "pubDate": f"{pub_dt.year}. {pub_dt.month}. {pub_dt.day}.",
                "title_korean": title,
                "description_raw": description,
                "source": extract_source(
                    item.get("originallink", ""), item.get("link", "")
                ),
                "link": item.get("link", ""),
                # Claude Code가 채울 컬럼 (빈값으로 남김)
                "summary_korean": "",
                "importance": "",
            })

        if stop:
            break
        start += 100
        time.sleep(0.1)

    return results


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main():
    date_from_dt = datetime.strptime(DATE_FROM, "%Y-%m-%d")
    date_to_dt   = datetime.strptime(DATE_TO,   "%Y-%m-%d")

    all_results = []
    seen_links  = set()

    keyword_groups = {
        "업종": INDUSTRY_KEYWORDS,
        "경기/구조": ECONOMY_KEYWORDS,
        "경쟁사": COMPETITOR_KEYWORDS,
        "트렌드": TREND_KEYWORDS,
    }

    for group_name, keywords in keyword_groups.items():
        print(f"\n▶ [{group_name}] 키워드 검색 시작")
        for kw in keywords:
            rows = fetch_keyword(kw, date_from_dt, date_to_dt)
            new = 0
            for r in rows:
                if r["link"] in seen_links:
                    continue
                seen_links.add(r["link"])
                all_results.append(r)
                new += 1
            print(f"  {kw}: {len(rows)}건 수집 / {new}건 신규 (누적 {len(all_results)}건)")

    # 최신순 상한 적용 (CAP_KEYWORDS는 검색 결과가 많아 최신 CAP_N건만 채택)
    def pub_key(r):
        y, m, d = [int(p) for p in r["pubDate"].replace(".", "").split()]
        return (y, m, d)

    by_kw = {}
    for r in all_results:
        by_kw.setdefault(r["search_keyword"], []).append(r)

    capped_results = []
    for kw, items in by_kw.items():
        if kw in CAP_KEYWORDS:
            items = sorted(items, key=pub_key, reverse=True)[:CAP_N]
        capped_results.extend(items)
    all_results = capped_results

    # CSV 저장
    fieldnames = [
        "search_keyword", "pubDate", "title_korean",
        "description_raw", "source", "link",
        "summary_korean", "importance",
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n✅ 1차 수집 완료: 총 {len(all_results)}건 → {OUTPUT_CSV}")
    print("\n" + "="*60)
    print("[Claude Code 다음 단계 지시]")
    print("="*60)
    print(MAIN_INTERESTS)
    print(f"""
위 기준에 따라 {OUTPUT_CSV}의 각 기사를 읽고:
1. summary_korean: 기사 핵심 두 마디 (description_raw 참고, 그대로 베끼지 말 것)
2. importance: ★ / ★★ / ★★★ (위 메인 관심사 기준)
를 채운 뒤, 아래 컬럼 순서로 엑셀(leisure_news_final.xlsx)을 생성할 것.

최종 컬럼 순서:
search_keyword | pubDate | title_korean | summary_korean | importance | source | link

엑셀 서식:
- 헤더: 배경 #305496, 흰 글씨, 굵게, 가운데 정렬
- 본문: Arial 10pt, 위쪽 정렬, 줄바꿈, 행 높이 60
- 열 너비: search_keyword(18) pubDate(11) title_korean(42) summary_korean(48) importance(8) source(14) link(38)
- link 컬럼: 하이퍼링크 처리 (파란색 밑줄)
- 1행 freeze, 전체 auto_filter 적용
- 파일명: leisure_news_final.xlsx
""")


if __name__ == "__main__":
    main()
