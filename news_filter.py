"""
뉴스 선별 & 평가 (2단계)
입력: naver_news_raw.csv
결과: news_filtered.csv

필요 환경변수:
  ANTHROPIC_API_KEY   Claude API 키
  NAVER_CLIENT_ID     (수집 시 사용, 이 스크립트에서는 불필요)
"""

import os
import csv
import json
import time
import re
import requests
from datetime import datetime

INPUT  = "naver_news_raw.csv"
OUTPUT = "news_filtered.csv"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY 환경변수를 설정하세요.")

# ── 제외 키워드 패턴 (규칙 기반 1차 필터) ────────────────
EXCLUDE_PATTERNS = [
    r"맛집",
    r"레시피",
    r"조리법",
    r"만드는 법",
    r"식재료 가격",
    r"농수산물 가격",
    r"원물 가격",
    r"식중독 (발생|신고|환자|사례)",
    r"리콜",
]
EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS))

# ── 핵심 관심사 (프롬프트에 전달) ────────────────────────
INTEREST_CONTEXT = """
핵심 관심사 (importance 판단 기준):
1. 식당 예약 시장 경쟁 (네이버 플레이스 예약, 캐치테이블 등 경쟁 구도)
2. 배달/주문 플랫폼 경쟁과 수수료 정책
3. 테이블오더/POS 시장
4. AI 에이전트의 예약/주문 실행 (해외 사례 포함)
5. 외식업 구조 변화 (양극화, 프랜차이즈 vs 개인식당, 소비 트렌드)

importance 기준:
- ★★★: 핵심 관심사 1~5에 직접 해당. 경쟁사(캐치테이블, 티오더 등)의 구체적 행동,
        수수료/규제 등 제도 변화로 사업자에게 즉각 영향
- ★★ : 외식업 전반의 경기/구조 배경 트렌드. 직접 영향은 아니지만 맥락상 알아둘 가치
- ★  : 검색 키워드는 걸렸지만 핵심 관심사와 실질적으로 무관 (노이즈)
- EXCLUDE: 아래 중 하나라도 해당하면 제외
    · 개별 맛집 리뷰, 레시피, 식재료 시세, 식품 리콜
    · 단일 식중독 사건 (제도/규제 변화 기사는 제외하지 않음)
    · 경쟁사(배달의민족·쿠팡이츠·요기요·캐치테이블·티오더 등)가 특정 지자체·기관과
      협약(MOU, 업무협약, 파트너십 체결)을 맺었다는 내용이 기사의 핵심인 경우
      → 단, 협약이 아니라 특정 지역·행사에서 신규 기능/서비스를 공개하거나
        실제 서비스를 출시한 내용(전략적 시사점이 있는 경우)은 제외하지 않고 포함
"""


def rule_based_exclude(title: str, description: str) -> bool:
    """True = 제외 대상"""
    text = title + " " + description
    return bool(EXCLUDE_RE.search(text))


def extract_source(link: str, original_link: str) -> str:
    """링크에서 언론사명 추출"""
    for url in [original_link, link]:
        if not url:
            continue
        m = re.search(r"https?://(?:www\.|m\.)?([^./]+)", url)
        if m:
            domain = m.group(1).lower()
            DOMAIN_MAP = {
                "chosun": "조선일보", "joongang": "중앙일보", "donga": "동아일보",
                "hani": "한겨레", "khan": "경향신문", "ohmynews": "오마이뉴스",
                "yonhap": "연합뉴스", "yna": "연합뉴스", "newsis": "뉴시스",
                "newsen": "뉴센", "news1": "뉴스1", "edaily": "이데일리",
                "etnews": "전자신문", "zdnet": "ZDNet Korea", "bloter": "블로터",
                "techm": "테크M", "venturesquare": "벤처스퀘어",
                "hankyung": "한국경제", "mk": "매일경제", "sedaily": "서울경제",
                "mt": "머니투데이", "fnnews": "파이낸셜뉴스", "inews24": "아이뉴스24",
                "dnews": "디지털데일리", "dt": "디지털타임스",
            }
            for key, name in DOMAIN_MAP.items():
                if key in domain:
                    return name
            return domain
    return ""


def format_pubdate(date_str: str) -> str:
    """'2026-06-04' → '2026. 6. 4.'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.year}. {dt.month}. {dt.day}."
    except Exception:
        return date_str


def call_claude(articles: list) -> list:
    """
    articles: [{"keyword":..., "title":..., "description":...}, ...]
    returns: [{"importance":..., "summary_korean":..., "exclude": bool}, ...]
    """
    prompt_items = "\n".join(
        f'[{i+1}] 키워드: {a["keyword"]}\n제목: {a["title"]}\n내용: {a["description"]}'
        for i, a in enumerate(articles)
    )

    system = f"""당신은 외식업/푸드테크 시장 동향을 분석하는 전문 애널리스트입니다.
아래 기사 목록을 보고 각 기사를 평가하세요.

{INTEREST_CONTEXT}

응답은 반드시 아래 JSON 배열 형식만 출력하세요 (다른 텍스트 없이):
[
  {{
    "idx": 1,
    "exclude": false,
    "importance": "★★★",
    "summary_korean": "두 문장 이내 핵심 요약"
  }},
  ...
]

summary_korean 작성 규칙:
- 기사 내용만 놓고 핵심 두 마디로 간결하게
- "우리 사업", "플레이스" 등 주관적 표현 금지
- description을 그대로 베끼지 말고 재구성
- exclude=true이면 summary_korean은 빈 문자열
"""

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": prompt_items}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["content"][0]["text"].strip()

    # JSON 파싱
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if m:
        return json.loads(m.group())
    return json.loads(content)


def deduplicate(rows: list) -> list:
    """제목 유사도 기반 간단 중복 제거: 제목 앞 20자가 같으면 첫 번째만 유지"""
    seen = {}
    result = []
    for row in rows:
        key = row["title_korean"][:20]
        if key not in seen:
            seen[key] = True
            result.append(row)
    return result


def main():
    # CSV 읽기
    with open(INPUT, newline="", encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))
    print(f"원본 기사: {len(raw_rows)}건")

    # 규칙 기반 1차 필터
    candidates = [r for r in raw_rows if not rule_based_exclude(r["title"], r["description"])]
    print(f"규칙 필터 후: {len(candidates)}건")

    # Claude API 2차 평가 (배치 10건씩)
    BATCH = 10
    evaluated = []

    for i in range(0, len(candidates), BATCH):
        batch = candidates[i:i + BATCH]
        print(f"  AI 평가 중... {i+1}~{min(i+BATCH, len(candidates))}번째", end="\r", flush=True)
        try:
            results = call_claude(batch)
            idx_map = {r["idx"]: r for r in results}
        except Exception as e:
            print(f"\n  배치 오류 ({i}~): {e}")
            # 오류 시 ★★로 기본값 처리
            idx_map = {j+1: {"idx": j+1, "exclude": False, "importance": "★★", "summary_korean": ""} for j in range(len(batch))}

        for j, article in enumerate(batch):
            ev = idx_map.get(j + 1, {})
            if ev.get("exclude", False):
                continue
            source = extract_source(article.get("link", ""), article.get("originallink", ""))
            evaluated.append({
                "search_keyword": article["keyword"],
                "pubDate":        format_pubdate(article["pubDate"]),
                "title_korean":   article["title"],
                "summary_korean": ev.get("summary_korean", ""),
                "importance":     ev.get("importance", "★"),
                "source":         source,
                "link":           article.get("link", ""),
            })
        time.sleep(0.5)

    print(f"\nAI 평가 완료: {len(evaluated)}건")

    # 중복 제거
    final = deduplicate(evaluated)
    print(f"중복 제거 후: {len(final)}건")

    # importance 분포 출력
    dist = {}
    for r in final:
        dist[r["importance"]] = dist.get(r["importance"], 0) + 1
    print("importance 분포:", " | ".join(f"{k}: {v}건" for k, v in sorted(dist.items(), reverse=True)))

    # CSV 저장
    fieldnames = ["search_keyword", "pubDate", "title_korean", "summary_korean", "importance", "source", "link"]
    with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final)

    print(f"\n저장 완료 → {OUTPUT}  ({len(final)}행)")


if __name__ == "__main__":
    main()
