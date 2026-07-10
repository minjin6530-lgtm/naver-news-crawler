"""
전체 업종 경쟁사 크롤링 실행
industries/competitors.py의 경쟁사 리스트를 업종별로 순서대로 검색.

사용법:
    export NAVER_CLIENT_ID="..."
    export NAVER_CLIENT_SECRET="..."

    # 전체 업종 경쟁사 한번에
    python run_competitors.py

    # 특정 업종만
    python run_competitors.py 식당
    python run_competitors.py 레저
"""

import sys
import naver_news_engine as engine
from industries.competitors import COMPETITORS
from industries.exclusions import INDUSTRY_EXCLUSIONS

# ── 설정 ────────────────────────────────────────────────────
DATE_FROM              = "2026-07-01"
DATE_TO                = "2026-07-09"
MAX_ARTICLES_PER_QUERY = 10
BATCH_SIZE             = 30
MAX_BATCHES_PER_RUN    = 8

# ── 경쟁사 기사 Claude Code 판단 기준 (전 업종 공통) ─────────
COMPETITOR_MAIN_INTERESTS = """
[경쟁사 기사 필터링 기준 — 전 업종 공통]

수집 기간 기사 중 아래 주제에 해당하는 기사만 포함. 해당 없으면 ★로 평가 후 제외.

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

[summary_korean 작성 규칙 — 각색 금지, 원문 핵심 내용 그대로]
- 문장 한 개
- 반드시 해당 기사 자신의 title_korean/description_raw에 명시적으로 쓰인
  내용만 사용. 각색·추론·배경지식·다른 기사 내용을 섞어 보태지 말 것
- description_raw는 "..."로 끊긴 발췌문이므로 잘린 뒤 내용을 추측하지 말 것
- 구체적 수치/데이터가 있으면 원문 표현 그대로 반드시 포함
- 플레이스 관점 관련 키워드(예약, 수수료, 플랫폼, AI 등) 있으면 포함
- '플레이스', '우리 사업' 표현 금지

예시: "카카오가 카나나 AI를 카카오톡에 통합해 장소 추천과 예약을 단일 흐름으로 연결, OTA 슈퍼앱 전략을 본격화했다."
"""


def build_config(category, keywords):
    excl       = INDUSTRY_EXCLUSIONS.get(category, {})
    extra_t    = excl.get("title", [])
    extra_c    = excl.get("context", [])
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
        "output_prefix":    f"competitor_{category}".replace("/", "_"),
    }


def main():
    # 실행할 업종 결정
    if len(sys.argv) >= 2:
        target = sys.argv[1]
        if target not in COMPETITORS:
            print(f"❌ 알 수 없는 업종: '{target}'")
            print(f"사용 가능: {list(COMPETITORS.keys())}")
            sys.exit(1)
        targets = {target: COMPETITORS[target]}
    else:
        targets = COMPETITORS

    all_batch_files = []
    for category, keywords in targets.items():
        print(f"\n{'='*60}")
        print(f"[경쟁사] {category} ({len(keywords)}개 경쟁사)")
        print(f"{'='*60}")
        config = build_config(category, keywords)
        engine.run(config)

    print("\n" + "="*60)
    print("전체 경쟁사 크롤링 완료")
    print("="*60)
    print("""
[Claude Code 최종 지시]
모든 업종의 competitor_*_batch*.csv 파일을 읽고 summary_korean, importance를
채운 뒤, ★★ / ★★★ 기사만 모든 업종을 합쳐 단일 엑셀(competitors_final.xlsx)
하나로 생성할 것. 하나의 파일, 하나의 시트로만 만들고 업종별로 별도 엑셀
파일(competitor_<업종>_final.xlsx 등)은 절대 만들지 않는다.

최종 컬럼 순서:
source_type | search_keyword | pubDate | title_korean | summary_korean | importance | source | link

엑셀 서식:
- 헤더: 배경 #305496, 흰 글씨, 굵게, 가운데 정렬
- 본문: Arial 10pt, 세로 가운데 정렬, 줄바꿈 없이 한 줄, 행 높이는 한 줄 크기
- 열 너비: 셀 내용이 잘리지 않도록 실제 텍스트 길이 기준으로 자동 산정
  (build_excel.py의 build_final_excel()이 처리)
- link 컬럼: 하이퍼링크 처리 (파란색 밑줄)
- 1행 freeze, 전체 auto_filter 적용
""")


if __name__ == "__main__":
    main()
