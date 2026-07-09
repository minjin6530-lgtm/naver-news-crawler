"""
openpyxl 없이 표준 라이브러리만으로 .xlsx(OOXML)를 생성하는 최소 기능 writer.
네트워크가 차단된 환경(외부 패키지 설치 불가)에서 경쟁사 리포트용 엑셀을
만들기 위한 용도로 작성됨. 지원 범위:
  - 헤더 행 서식(배경색, 굵게, 흰 글씨, 가운데 정렬)
  - 본문 서식(글꼴, 줄바꿈, 위쪽 정렬, 행 높이)
  - 열 너비 지정
  - link 컬럼 실제 하이퍼링크(파란색 밑줄)
  - 1행 freeze, 전체 autofilter
"""

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
  <alignment vertical="top" wrapText="1"/>
</xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">
  <alignment horizontal="center" vertical="center"/>
</xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">
  <alignment vertical="top" wrapText="1"/>
</xf>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">
  <alignment vertical="top" wrapText="1"/>
</xf>
</cellXfs>
</styleSheet>"""

STYLE_HEADER = 1
STYLE_BODY = 2
STYLE_LINK = 3


def write_xlsx(path, headers, col_widths, rows, link_col, row_height=60):
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
    sheet_rows = ['<row r="1" ht="20" customHeight="1">%s</row>' % header_cells]

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


FINAL_HEADERS = [
    "source_type", "search_keyword", "pubDate", "title_korean",
    "summary_korean", "importance", "source", "link",
]
FINAL_COL_WIDTHS = {
    "source_type": 8, "search_keyword": 18, "pubDate": 11, "title_korean": 42,
    "summary_korean": 48, "importance": 8, "source": 14, "link": 38,
}


def build_final_excel(path, rows):
    """rows: FINAL_HEADERS 키를 가진 dict 리스트 (importance ★★ 이상만 포함되어야 함)"""
    write_xlsx(path, FINAL_HEADERS, FINAL_COL_WIDTHS, rows, link_col="link")
