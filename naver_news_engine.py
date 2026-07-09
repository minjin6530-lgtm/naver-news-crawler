"""
네이버 뉴스 검색 API — 공통 크롤링 엔진
모든 업종이 공유하는 로직(제외 필터, 중복 제거, 뉴스사 우선순위, 배치 저장)을 담당.

업종별 설정은 industries/ 폴더의 각 파일에서 정의.
실행은 run_single.py (단일 업종) 또는 run_all.py (전체 업종) 사용.
"""

import os, re, csv, time, html, json
import urllib.request, urllib.parse
from datetime import datetime
from email.utils import parsedate_to_datetime
from collections import defaultdict

# ──────────────────────────────────────────────────────────────
# 공통 제외 키워드 — 레이어 1: 제목에 포함 시 즉시 제외
# ──────────────────────────────────────────────────────────────
EXCLUDE_TITLE_KEYWORDS = [
    # 단순 이벤트·프로모션 홍보
    "이벤트 진행", "이벤트 연다", "스페셜 이벤트",
    "축제 진행", "행사 진행", "행사 연다", "프로그램 진행",
    # 단순 할인·티켓 안내
    "이용권 할인", "이용권 증정", "입장권 할인", "반값 할인", "할인 쿠폰",
    # 연예인·아이돌 콜라보 / 팬덤 기사
    "콜라보", "콜라보레이션", "팬들", "성지순례", "목격담", "코스프레",
    # 장소 추천·나들이 코스
    "어디 갈까", "나들이 코스", "여행지 추천", "여행 코스", "여가 장소", "여행 에세이",
    # 항공·교통 단순 정보
    "항공권 할인", "항공 노선", "항공사 실적",
    # 완전 무관 칼럼·인물·유통 섹션
    "[Who Is", "[유통레이더]", "더봄]",
    # 기타
    "맛집", "숙소 추천", "호텔 추천",
]

# ──────────────────────────────────────────────────────────────
# 공통 제외 키워드 — 레이어 2: 제목+설명 모두 확인 후 제외
# ──────────────────────────────────────────────────────────────
EXCLUDE_CONTEXT_KEYWORDS = [
    "생리대", "코스피", "주가",
]

# ──────────────────────────────────────────────────────────────
# 지역 기사 제외 패턴 (전 업종 공통)
# ──────────────────────────────────────────────────────────────
REGIONAL_EXCLUDE_PATTERNS = [
    "부산관광공사", "인천관광공사", "경기관광공사", "강원관광공사",
    "충북관광공사", "충남관광공사", "전북관광공사", "전남관광공사",
    "경북관광공사", "경남관광공사", "제주관광공사", "대구관광공사",
    "광주관광공사", "대전관광공사", "울산관광공사", "세종관광공사",
    "지역 관광 활성화", "지역 관광 활성", "지역 경제 활성화",
    "시, 관광 활성", "군, 관광 활성", "구, 관광 활성",
]

# ──────────────────────────────────────────────────────────────
# 뉴스사 우선순위 (중복 시 선별 기준, 전 업종 공통)
# 티어 1 = 주요뉴스사 / 2 = IT뉴스사 / 3 = 특수뉴스사 / 4 = 기타
# ──────────────────────────────────────────────────────────────
SOURCE_PRIORITY = {
    # 티어 1: 주요 뉴스사
    "kyunghyang.com": 1, "kmib.co.kr": 1, "donga.com": 1,
    "munhwa.com": 1, "asiatoday.co.kr": 1, "seoul.co.kr": 1,
    "segye.com": 1, "news1.kr": 1, "newsis.com": 1,
    "chosun.com": 1, "hani.co.kr": 1, "hankookilbo.com": 1,
    "joongang.co.kr": 1, "hankyung.com": 1, "nocutnews.co.kr": 1,
    "sisain.co.kr": 1, "heraldcorp.com": 1, "yna.co.kr": 1,
    "mk.co.kr": 1, "mt.co.kr": 1, "edaily.co.kr": 1,
    "fnnews.com": 1, "businesspost.co.kr": 1,
    # 티어 2: IT 뉴스사
    "ddaily.co.kr": 2, "etnews.com": 2, "zdnet.co.kr": 2,
    "bloter.net": 2, "platum.kr": 2, "venturesquare.net": 2,
    "thebell.co.kr": 2, "itchosun.com": 2, "rocketpunch.com": 2,
    # 티어 3: 업종별 특수 뉴스사
    "travelnews.co.kr": 3, "traveldaily.co.kr": 3, "tourkorea.or.kr": 3,  # 레저/여행
    "dailyvet.co.kr": 3, "kvma.or.kr": 3,                                  # 동물병원
    "msik.kr": 3, "foodtoday.or.kr": 3,                                    # 외식
    "cosmorning.com": 3, "dailycosmetic.com": 3,                           # 뷰티
    "hotelrestaurant.co.kr": 3,                                             # 숙박
    "docdocdoc.co.kr": 3, "medicaltimes.com": 3, "hitnews.co.kr": 3,       # 의료
}

API_URL = "https://openapi.naver.com/v1/search/news.json"


# ──────────────────────────────────────────────────────────────
# 헬퍼 함수
# ──────────────────────────────────────────────────────────────
def strip_tags(text):
    text = re.sub(r"</?b>", "", text)
    return html.unescape(text).strip()


def is_excluded(title, description, extra_title_kws=None, extra_context_kws=None):
    """
    공통 제외 필터 + 업종별 추가 제외 키워드 지원
    extra_title_kws: 업종별 추가 제목 제외 키워드 리스트
    extra_context_kws: 업종별 추가 컨텍스트 제외 키워드 리스트
    """
    title_kws = EXCLUDE_TITLE_KEYWORDS + (extra_title_kws or [])
    context_kws = EXCLUDE_CONTEXT_KEYWORDS + (extra_context_kws or [])

    if any(kw in title for kw in title_kws):
        return True
    if any(kw in title for kw in REGIONAL_EXCLUDE_PATTERNS):
        return True
    combined = f"{title} {description}"
    if any(kw in combined for kw in context_kws):
        return True
    return False


def extract_source(original_link, link):
    url = original_link or link
    try:
        return url.split("//")[-1].split("/")[0].replace("www.", "")
    except:
        return ""


def get_source_tier(source_domain):
    for domain, tier in SOURCE_PRIORITY.items():
        if domain in source_domain:
            return tier
    return 4


def count_numbers(text):
    return len(re.findall(r'\d+', text))


def extract_title_tokens(title):
    cleaned = re.sub(r"[^\w\s]", " ", title)
    return set(w for w in cleaned.split() if len(w) >= 2)


def jaccard_similarity(set_a, set_b):
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ──────────────────────────────────────────────────────────────
# 핵심 크롤링 함수
# ──────────────────────────────────────────────────────────────
def fetch_keyword(keyword, date_from_dt, date_to_dt, source_type="업종",
                  max_articles=None, extra_title_kws=None, extra_context_kws=None):
    client_id     = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수를 설정하세요.")

    results = []
    start = 1

    while start <= 1000:
        params = {"query": keyword, "display": 100, "start": start, "sort": "date"}
        url = API_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", client_id)
        req.add_header("X-Naver-Client-Secret", client_secret)

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

            title       = strip_tags(item["title"])
            description = strip_tags(item["description"])

            if is_excluded(title, description, extra_title_kws, extra_context_kws):
                continue

            results.append({
                "source_type":    source_type,
                "search_keyword": keyword,
                "pubDate":        f"{pub_dt.year}. {pub_dt.month}. {pub_dt.day}.",
                "title_korean":   title,
                "description_raw": description,
                "source":         extract_source(item.get("originallink", ""), item.get("link", "")),
                "link":           item.get("link", ""),
                "summary_korean": "",
                "importance":     "",
            })

            if max_articles and len(results) >= max_articles:
                stop = True
                break

        if stop:
            break
        start += 100
        time.sleep(0.1)

    return results


# ──────────────────────────────────────────────────────────────
# 중복 제거 (소스 티어 + 수치 데이터 기준)
# ──────────────────────────────────────────────────────────────
def deduplicate(articles, threshold=0.35):
    """
    선별 우선순위:
    1. 뉴스사 티어 (1=주요 > 2=IT > 3=특수 > 4=기타)
    2. 수치 데이터 많은 기사
    3. 제목 길이
    """
    groups = defaultdict(list)
    for art in articles:
        key = (art["pubDate"], art["search_keyword"])
        groups[key].append(art)

    result = []
    for key, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        token_sets = [extract_title_tokens(a["title_korean"]) for a in group]
        clusters = []

        for i in range(len(group)):
            placed = False
            for cluster in clusters:
                if jaccard_similarity(token_sets[i], token_sets[cluster[0]]) >= threshold:
                    cluster.append(i)
                    placed = True
                    break
            if not placed:
                clusters.append([i])

        for cluster in clusters:
            best = min(
                cluster,
                key=lambda i: (
                    get_source_tier(group[i]["source"]),
                    -count_numbers(group[i]["description_raw"]),
                    -len(group[i]["title_korean"]),
                )
            )
            result.append(group[best])

    return result


# ──────────────────────────────────────────────────────────────
# 배치 저장
# ──────────────────────────────────────────────────────────────
FIELDNAMES = [
    "source_type", "search_keyword", "pubDate", "title_korean",
    "description_raw", "source", "link", "summary_korean", "importance",
]

def save_batches(articles, output_prefix, batch_size, max_batches):
    total        = len(articles)
    max_articles = batch_size * max_batches
    processed    = articles[:max_articles]
    batches      = [processed[i:i+batch_size] for i in range(0, len(processed), batch_size)]

    batch_files = []
    for idx, batch in enumerate(batches, start=1):
        fname = f"{output_prefix}_batch{idx:02d}.csv"
        with open(fname, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(batch)
        batch_files.append(fname)
        print(f"  배치 {idx:02d}: {len(batch)}건 → {fname}")

    if total > max_articles:
        print(f"\n⚠️  전체 {total}건 중 {max_articles}건만 저장 "
              f"(batch_size={batch_size} × max_batches={max_batches}). "
              f"나머지 {total - max_articles}건 제외. MAX_BATCHES_PER_RUN을 늘리세요.")

    print(f"\n✅ 완료: 전체 {total}건 / 저장 {len(processed)}건 / {len(batches)}개 배치")
    return batch_files


# ──────────────────────────────────────────────────────────────
# 단일 업종 실행 (외부에서 호출)
# ──────────────────────────────────────────────────────────────
def run(config: dict):
    """
    config 필수 키:
        category             str  업종명 (예: "레저")
        date_from            str  "YYYY-MM-DD"
        date_to              str  "YYYY-MM-DD"
        keyword_groups       list [(group_label, source_type, [keywords]), ...]
        main_interests       str  Claude Code 지시문용 텍스트
        output_prefix        str  배치 파일명 접두어 (예: "leisure")

    config 선택 키:
        max_articles_per_query  int  기본 10
        batch_size              int  기본 30
        max_batches_per_run     int  기본 8
        extra_title_kws         list 업종별 추가 제목 제외 키워드
        extra_context_kws       list 업종별 추가 컨텍스트 제외 키워드
        dedup_threshold         float 기본 0.35
    """
    category       = config["category"]
    date_from_dt   = datetime.strptime(config["date_from"], "%Y-%m-%d")
    date_to_dt     = datetime.strptime(config["date_to"],   "%Y-%m-%d")
    max_articles   = config.get("max_articles_per_query", 10)
    batch_size     = config.get("batch_size", 30)
    max_batches    = config.get("max_batches_per_run", 8)
    threshold      = config.get("dedup_threshold", 0.35)
    extra_t_kws    = config.get("extra_title_kws", [])
    extra_c_kws    = config.get("extra_context_kws", [])
    output_prefix  = config.get("output_prefix", category.lower())
    main_interests = config.get("main_interests", "")

    print(f"\n{'='*60}")
    print(f"[{category}] 크롤링 시작 | {config['date_from']} ~ {config['date_to']}")
    print(f"{'='*60}")

    all_results = []
    seen_links  = set()

    for group_label, source_type, keywords in config["keyword_groups"]:
        print(f"\n▶ [{group_label}] (source_type={source_type})")
        for kw in keywords:
            rows = fetch_keyword(
                kw, date_from_dt, date_to_dt,
                source_type=source_type,
                max_articles=max_articles,
                extra_title_kws=extra_t_kws,
                extra_context_kws=extra_c_kws,
            )
            new = 0
            for r in rows:
                if r["link"] in seen_links:
                    continue
                seen_links.add(r["link"])
                # category 컬럼은 run() 단계에서 주입
                r["category"] = category
                all_results.append(r)
                new += 1
            print(f"  {kw}: {len(rows)}건 / {new}건 신규 (누적 {len(all_results)}건)")

    # 중복 제거
    before = len(all_results)
    all_results = deduplicate(all_results, threshold=threshold)
    print(f"\n📌 중복 제거: {before}건 → {len(all_results)}건 (제거 {before - len(all_results)}건)")

    # 배치 저장
    batch_files = save_batches(all_results, output_prefix, batch_size, max_batches)

    # Claude Code 다음 단계 지시 출력
    print("\n" + "="*60)
    print("[Claude Code 다음 단계 지시]")
    print("="*60)
    print(main_interests)
    print(f"""
배치 파일 목록: {batch_files}

각 배치 파일을 순서대로 읽고 아래 순서로 처리할 것:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1. importance 평가 (★ / ★★ / ★★★)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
위 메인 관심사 기준으로 평가.
★ (노이즈) 로 판단된 기사는 최종 결과에서 완전히 제외. 행 자체를 삭제할 것.
★★ / ★★★ 기사만 다음 단계로 진행.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2. summary_korean 작성 (★★ / ★★★ 기사만)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[작성 규칙]
- 문장 한 개로 작성
- 기사 제목만으로 알 수 없는 주요 내용을 요약
- 플레이스 관점에서 중요한 키워드(예약, 수수료, 수요 변화, 플랫폼 전략 등)가 있으면 반드시 포함
- 수치/데이터가 있으면 그대로 포함
- '플레이스', '우리 사업' 표현 사용 금지
- description_raw를 참고하되 그대로 베끼지 말 것

[작성 예시]
"항공료 상승으로 한국 여행 수요가 위축될 우려가 있으며, 이미 여행사를 통한 단체 여행객은 줄어드는 추세다."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3. 특수 뉴스사 추가 필터링
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
특수 뉴스사(여행신문, 데일리벳, 월간식당 등) 기사 중 아래는 추가 제외:
- 자영업자·사업자 대상 경영 가이드 기사
- 네이버 플레이스와 직접 연관 없는 업계 내부용 기사
- 전국 단위 트렌드가 아닌 특정 지역 1~2개만 다루는 기사

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4. 최종 엑셀 생성
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
모든 배치 처리 후 ★★ / ★★★ 기사만 하나의 엑셀(파일명: {output_prefix}_final.xlsx)로 합칠 것.

최종 컬럼 순서:
source_type | search_keyword | pubDate | title_korean | summary_korean | importance | source | link

엑셀 서식:
- 헤더: 배경 #305496, 흰 글씨, 굵게, 가운데 정렬
- 본문: Arial 10pt, 위쪽 정렬, 줄바꿈, 행 높이 60
- 열 너비: source_type(8) search_keyword(18) pubDate(11) title_korean(42) summary_korean(48) importance(8) source(14) link(38)
- link 컬럼: 하이퍼링크 처리 (파란색 밑줄)
- 1행 freeze, 전체 auto_filter 적용
""")

    return all_results
