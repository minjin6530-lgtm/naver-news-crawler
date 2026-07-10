"""
경쟁사 전체 크롤링 — 2026년 6월 26일~30일
전체 9개 업종 경쟁사를 한번에 수집.

사용법:
    export NAVER_CLIENT_ID="..."
    export NAVER_CLIENT_SECRET="..."
    python run_competitors_june.py

    # 특정 업종만 실행
    python run_competitors_june.py 식당
"""

import sys
import naver_news_engine as engine
from industries.competitors import COMPETITORS
from industries.exclusions import INDUSTRY_EXCLUSIONS

# ── 이 파일 전용 설정 ────────────────────────────────────────
DATE_FROM              = "2026-06-26"
DATE_TO                = "2026-06-30"
MAX_ARTICLES_PER_QUERY = 100  # 키워드당 최대 100건으로 확대
BATCH_SIZE             = 30
MAX_BATCHES_PER_RUN    = 15   # 배치 수도 넉넉하게

COMPETITOR_MAIN_INTERESTS = """
[경쟁사 기사 필터링 기준 — 전 업종 공통]

포함 기준 (★★ 이상):
  - 경쟁사 전략 변화 (사업 확장, 신규 시장 진출, 철수/축소)
  - 기술 도입 (AI, 자동화, 데이터 분석 등 신기술 적용)
  - 신기능 출시 (예약/주문/결제 기능 신규 또는 개편)
  - 서비스 개편 (플랫폼 구조 변경, UX 개선, 제휴 확대)
  - 실적/매출 발표 (구체적 수치 포함 시 ★★★)

제외 기준 (★ → 결과에서 삭제):
  - 단순 채용 공고, 인사 발령
  - 주가·IR 자료 단순 보도 (수치 없이 주가만 언급)
  - 경쟁사 이름이 단순 언급된 무관 기사
  - 대표/임원 개인 인터뷰 (사업 전략 내용 없는 경우)

[summary_korean 작성 규칙]
- 문장 한 개
- 기사 제목만으로 알 수 없는 주요 내용 요약
- 구체적 수치/데이터 있으면 반드시 포함
- 플레이스 관점 키워드(예약, 수수료, 플랫폼, AI 등) 있으면 포함
- '플레이스', '우리 사업' 표현 금지

예시: "카카오가 카나나 AI를 카카오톡에 통합해 장소 추천과 예약을 단일 흐름으로 연결, OTA 슈퍼앱 전략을 본격화했다."
"""


def build_config(category, keywords):
    excl        = INDUSTRY_EXCLUSIONS.get(category, {})
    extra_t     = excl.get("title", [])
    extra_c     = excl.get("context", [])
    claude_note = excl.get("claude_note", "")

    interests = COMPETITOR_MAIN_INTERESTS
    if claude_note:
        interests += f"\n[{category} 업종 추가 판단 기준]\n{claude_note}\n"

    return {
        "category":               category,
        "date_from":              DATE_FROM,
        "date_to":                DATE_TO,
        "max_articles_per_query": MAX_ARTICLES_PER_QUERY,
        "batch_size":             BATCH_SIZE,
        "max_batches_per_run":    MAX_BATCHES_PER_RUN,
        "keyword_groups": [
            ("경쟁사", "경쟁사", keywords),
        ],
        "extra_title_kws":  extra_t,
        "extra_context_kws": extra_c,
        "main_interests":   interests,
        "output_prefix":    f"competitor_june_{category}",
    }


def main():
    if len(sys.argv) >= 2:
        target = sys.argv[1]
        if target not in COMPETITORS:
            print(f"❌ 알 수 없는 업종: '{target}'")
            print(f"사용 가능: {list(COMPETITORS.keys())}")
            sys.exit(1)
        targets = {target: COMPETITORS[target]}
    else:
        targets = COMPETITORS

    for category, keywords in targets.items():
        print(f"\n{'='*60}")
        print(f"[경쟁사] {category} ({len(keywords)}개) | {DATE_FROM} ~ {DATE_TO}")
        print(f"{'='*60}")
        engine.run(build_config(category, keywords))

    print("\n" + "="*60)
    print("전체 경쟁사 크롤링 완료 (6월 26~30일)")
    print("="*60)
    print("""
[Claude Code 최종 지시]
각 업종별 competitor_june_*_batch*.csv 파일을 읽고
summary_korean, importance 채운 뒤
전체를 하나의 엑셀(competitors_june_final.xlsx)로 합칠 것.

최종 컬럼 순서 (고정 서식 — build_excel.py FINAL_HEADERS):
source_type | search_keyword | pubDate | title_korean | link | importance | source | summary_korean

엑셀 서식:
- 헤더: 배경 #305496, 흰 글씨, 굵게, 가운데 정렬
- 본문: Arial 10pt, 세로 가운데 정렬, 줄바꿈 없이 한 줄, 행 높이는 한 줄 크기
- 열 너비: title_korean 등은 내용이 잘리지 않도록 자동 산정, link는 좁게(10),
  summary_korean은 폭을 줄여 고정(50) — build_excel.py의 build_final_excel()이 처리
- link 컬럼: 하이퍼링크 처리 (파란색 밑줄)
- 1행 freeze, 전체 auto_filter 적용
- 하나의 시트, 시트 분리 없음
""")


if __name__ == "__main__":
    main()
