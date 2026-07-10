"""
openpyxl 없이 표준 라이브러리만으로 .xlsx(OOXML)를 생성하는 최소 기능 writer.
네트워크가 차단된 환경(외부 패키지 설치 불가)에서 경쟁사 리포트용 엑셀을
만들기 위한 용도로 작성됨. 지원 범위:
  - 헤더 행 서식(배경색, 굵게, 흰 글씨, 가운데 정렬)
  - 본문 서식(글꼴, 세로 가운데 정렬, 줄바꿈 없는 한 줄 행 높이)
  - 열 너비 자동 산정(내용이 잘리지 않도록 실제 텍스트 길이 기준)
  - link 컬럼 실제 하이퍼링크(파란색 밑줄)
  - 1행 freeze, 전체 autofilter
"""

import unicodedata
import zipfile
from xml.sax.saxutils import escape, quoteattr


def _col_letter(idx: int) -> str:
    letters = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _esc(text: str) -> str:
    return escape("" if text is None else str(text))


def _display_width(text) -> float:
    """한글 등 전각 문자는 반각의 약 2배 폭으로 계산 (열 너비 자동 산정용)."""
    text = "" if text is None else str(text)
    width = 0.0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


EXCEL_MAX_COL_WIDTH = 255  # OOXML/Excel의 열 너비 상한


def auto_col_widths(headers, rows, min_width=8, padding=2):
    """각 컬럼의 헤더/본문 중 가장 넓은 셀 기준으로 열 너비를 계산해
    잘리는 셀 없이 한 줄에 다 보이도록 한다. Excel 열 너비 상한(255)은 넘지 않는다."""
    widths = {}
    for h in headers:
        longest = _display_width(h)
        for row in rows:
            longest = max(longest, _display_width(row.get(h, "")))
        widths[h] = min(EXCEL_MAX_COL_WIDTH, max(min_width, longest + padding))
    return widths


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3">
<font><sz val="10"/><name val="Arial"/></font>
<font><sz val="10"/><name val="Arial"/><b/><color rgb="FFFFFFFF"/></font>
<font><sz val="10"/><name val="Arial"/><color rgb="FF0563C1"/><u/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF305496"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0">
  <alignment vertical="center"/>
</xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">
  <alignment horizontal="center" vertical="center"/>
</xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">
  <alignment vertical="center"/>
</xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
  <alignment vertical="center"/>
</xf>
</cellXfs>
</styleSheet>"""

STYLE_HEADER = 1
STYLE_BODY = 2
STYLE_LINK = 3


def write_xlsx(path, headers, col_widths, rows, link_col, row_height=15):
    """
    headers: [str, ...] 컬럼명 (표시 순서)
    col_widths: {header: width}
    rows: [{header: value, ...}, ...]
    link_col: 하이퍼링크로 처리할 컬럼명 (셀 값이 URL)
    """
    ncols = len(headers)
    nrows = len(rows)

    cols_xml = "".join(
        '<col min="%d" max="%d" width="%s" customWidth="1"/>'
        % (i + 1, i + 1, col_widths.get(h, 15))
        for i, h in enumerate(headers)
    )

    header_cells = "".join(
        '<c r="%s1" t="inlineStr" s="%d"><is><t xml:space="preserve">%s</t></is></c>'
        % (_col_letter(i), STYLE_HEADER, _esc(h))
        for i, h in enumerate(headers)
    )
    sheet_rows = ['<row r="1" ht="%d" customHeight="1">%s</row>' % (row_height, header_cells)]

    hyperlinks = []
    rels = []
    rid_n = 1

    for r_idx, row in enumerate(rows, start=2):
        cells = []
        for c_idx, h in enumerate(headers):
            ref = "%s%d" % (_col_letter(c_idx), r_idx)
            value = row.get(h, "")
            if h == link_col and value:
                rid = "rId%d" % rid_n
                rid_n += 1
                rels.append(
                    '<Relationship Id="%s" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
                    'Target=%s TargetMode="External"/>' % (rid, quoteattr(str(value)))
                )
                hyperlinks.append('<hyperlink ref="%s" r:id="%s"/>' % (ref, rid))
                cells.append(
                    '<c r="%s" t="inlineStr" s="%d"><is><t xml:space="preserve">%s</t></is></c>'
                    % (ref, STYLE_LINK, _esc(value))
                )
            else:
                cells.append(
                    '<c r="%s" t="inlineStr" s="%d"><is><t xml:space="preserve">%s</t></is></c>'
                    % (ref, STYLE_BODY, _esc(value))
                )
        sheet_rows.append(
            '<row r="%d" ht="%d" customHeight="1">%s</row>' % (r_idx, row_height, "".join(cells))
        )

    dimension = "A1:%s%d" % (_col_letter(ncols - 1), nrows + 1)

    hyperlinks_xml = ""
    if hyperlinks:
        hyperlinks_xml = "<hyperlinks>%s</hyperlinks>" % "".join(hyperlinks)

    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
           xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<dimension ref="%s"/>
<sheetViews>
<sheetView workbookViewId="0">
<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
</sheetView>
</sheetViews>
<cols>%s</cols>
<sheetData>%s</sheetData>
<autoFilter ref="%s"/>
%s
</worksheet>""" % (dimension, cols_xml, "".join(sheet_rows), dimension, hyperlinks_xml)

    sheet_rels_xml = ""
    if rels:
        sheet_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
%s
</Relationships>""" % "".join(rels)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK_XML)
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        z.writestr("xl/styles.xml", STYLES_XML)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if sheet_rels_xml:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels_xml)


# 표준 서식 (사용자 요청 기준 고정 — 이후 파일 요청 시 항상 이 순서/너비를 따른다)
FINAL_HEADERS = [
    "source_type", "search_keyword", "pubDate", "title_korean",
    "link", "importance", "source", "summary_korean",
]

# title_korean/source_type/search_keyword/pubDate/importance/source는 내용 기준
# 자동 너비. link는 클릭해서 이동하는 용도라 좁게, summary_korean은 한눈에
# 훑어보도록 폭을 줄여 고정한다 (내용 전체는 셀에 남아있고 필요하면 셀 너비만
# 늘리면 됨. 자동 줄바꿈은 쓰지 않음).
FINAL_COL_OVERRIDES = {
    "link": 10,
    "summary_korean": 50,
}


def build_final_excel(path, rows):
    """rows: FINAL_HEADERS 키를 가진 dict 리스트 (importance ★★ 이상만 포함되어야 함).
    열 순서/너비는 FINAL_HEADERS·FINAL_COL_OVERRIDES 기준 고정 서식을 따른다."""
    col_widths = auto_col_widths(FINAL_HEADERS, rows)
    col_widths.update(FINAL_COL_OVERRIDES)
    write_xlsx(path, FINAL_HEADERS, col_widths, rows, link_col="link", row_height=15)
