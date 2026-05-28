from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import re

from .detector import (
    DIRECTOR_EMOLUMENTS_KEYWORDS,
    NON_COMFORT_KEYWORDS,
    find_numeric_hits,
    is_non_comfort_context,
)


@dataclass(frozen=True)
class Finding:
    page: int
    text: str
    reason: str
    context: str


@dataclass(frozen=True)
class SectionState:
    name: str
    policy: str


PROCESS_ALL = "process_all"
PROCESS_ISSUER_REVENUE_ONLY = "issuer_revenue_only"
PROCESS_DIRECTOR_EMOLUMENTS_ONLY = "director_emoluments_only"
SKIP_SECTION = "skip_section"


def mark_pdf(
    input_pdf: Path,
    output_pdf: Path,
    *,
    csv_path: Path | None = None,
    mode: str = "conservative",
    table_regions: bool = True,
    stroke_width: float = 0.8,
) -> list[Finding]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required. Install with `pip install -e .` or `pip install pymupdf`."
        ) from exc

    document = fitz.open(input_pdf)
    findings: list[Finding] = []
    section = SectionState("unknown", SKIP_SECTION)

    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        section = update_section_state(section, page_text)
        if should_skip_page(page_text, section):
            continue

        words = page.get_text("words")
        lines = group_words_by_line(words)
        numeric_regions = detect_table_numeric_regions(fitz, lines) if table_regions else []
        numeric_regions = [
            region
            for region in numeric_regions
            if should_process_table_region(page_text, region, section)
        ]
        numeric_regions = merge_table_regions(fitz, numeric_regions)

        for region in numeric_regions:
            annot = page.add_rect_annot(region.rect)
            annot.set_colors(stroke=(1, 0, 0))
            annot.set_border(width=stroke_width)
            annot.update()
            findings.append(
                Finding(
                    page=page_index + 1,
                    text=f"table numeric region ({region.row_count} rows)",
                    reason="financial table numeric area",
                    context=region.context,
                )
            )

        for line_words in lines:
            line_text = join_words(line_words)
            if not should_process_line(line_text, section):
                continue
            hits = find_numeric_hits(line_text, mode=mode)
            if not hits:
                continue

            for hit in hits:
                rects = rectangles_for_hit(fitz, line_words, line_text, hit.start, hit.end)
                rects = [
                    rect
                    for rect in rects
                    if not any(rect_center_inside(rect, region.rect) for region in numeric_regions)
                ]
                if not rects:
                    continue

                for rect in rects:
                    annot = page.add_rect_annot(rect)
                    annot.set_colors(stroke=(1, 0, 0))
                    annot.set_border(width=stroke_width)
                    annot.update()

                findings.append(
                    Finding(
                        page=page_index + 1,
                        text=hit.text,
                        reason=hit.reason,
                        context=compact_context(line_text),
                    )
                )

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_pdf, garbage=4, deflate=True)
    document.close()

    if csv_path:
        write_findings_csv(csv_path, findings)

    return findings


@dataclass(frozen=True)
class TableRegion:
    rect: object
    row_count: int
    context: str


APPENDIX_KEYWORDS = (
    "appendix",
    "appendices",
    "附录",
    "附錄",
)


CORE_SECTION_PATTERNS = (
    ("summary", "summary"),
    ("this summary aims to give you an overview of the information contained in this", "summary"),
    ("this summary aims to give you an overview of the information contained in this prospectus", "summary"),
    ("risk factors", "risk factors"),
    ("business", "business"),
    ("financial information", "financial information"),
    ("discussion of certain key items from our consolidated statements of financial position", "financial information"),
    ("概要", "summary"),
    ("摘要", "summary"),
    ("风险因素", "risk factors"),
    ("風險因素", "risk factors"),
    ("业务", "business"),
    ("業務", "business"),
    ("财务资料", "financial information"),
    ("財務資料", "financial information"),
)

INDUSTRY_SECTION_PATTERNS = (
    "industry overview",
    "行业概览",
    "行業概覽",
)

DIRECTOR_SECTION_PATTERNS = (
    "directors and senior management",
    "directors, supervisors and senior management",
    "statutory and general information",
    "董事及高级管理层",
    "董事、监事及高级管理层",
    "董事及高級管理層",
    "董事、監事及高級管理層",
    "法定及一般资料",
    "法定及一般資料",
)

STOP_SECTION_PATTERNS = (
    "history, reorganization and corporate structure",
    "regulatory overview",
    "directors and parties involved in the global offering",
    "corporate information",
    "relationship with our controlling shareholders",
    "connected transactions",
    "share capital",
    "substantial shareholders",
    "cornerstone investors",
    "the cornerstone placing",
    "cornerstone placing",
    "our cornerstone investors",
    "future plans and use of proceeds",
    "underwriting",
    "structure of the global offering",
    "how to apply",
    "appendix",
    "appendices",
    "附录",
    "附錄",
)


def update_section_state(current: SectionState, page_text: str) -> SectionState:
    headings = get_page_heading_candidates(page_text)
    if not headings:
        return current

    if any(heading_matches(line, pattern) for line in headings[:12] for pattern in DIRECTOR_SECTION_PATTERNS):
        return SectionState("directors/statutory", PROCESS_DIRECTOR_EMOLUMENTS_ONLY)
    if any(heading_matches(line, pattern) for line in headings[:12] for pattern in STOP_SECTION_PATTERNS):
        return SectionState("other", SKIP_SECTION)
    if any(heading_matches(line, pattern) for line in headings[:12] for pattern in INDUSTRY_SECTION_PATTERNS):
        return SectionState("other", SKIP_SECTION)
    joined_headings = normalize_heading_text(" ".join(headings[:14]))
    if "discussion of certain key items from our consolidated statements of financial position" in joined_headings:
        return SectionState("financial information", PROCESS_ALL)
    for pattern, section_name in CORE_SECTION_PATTERNS:
        if any(heading_matches(line, pattern) for line in headings):
            return SectionState(section_name, PROCESS_ALL)
    return current


def get_page_heading_candidates(page_text: str) -> list[str]:
    lines = [line.strip().lower() for line in page_text.splitlines() if line.strip()]
    candidates: list[str] = []
    for line in [*lines[:18], *lines[-10:]]:
        cleaned = re.sub(r"\s+", " ", line)
        if len(cleaned) <= 110 and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def heading_matches(line: str, pattern: str) -> bool:
    if is_table_of_contents_line(line):
        return False
    normalized_line = normalize_heading_text(line)
    normalized_pattern = normalize_heading_text(pattern)
    if normalized_line == normalized_pattern:
        return True
    if normalized_line.startswith(f"{normalized_pattern} "):
        trailing = normalized_line[len(normalized_pattern) :].strip()
        return bool(re.fullmatch(r"[ivxlcdm0-9.() -]+", trailing))
    return False


def is_table_of_contents_line(line: str) -> bool:
    return ". ." in line or re.search(r"\.{3,}", line)


def normalize_heading_text(text: str) -> str:
    cleaned = re.sub(r"[\u0000-\u001f]+", " ", text.lower())
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff&/,'’ -]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" -")


def should_skip_page(page_text: str, section: SectionState | None = None) -> bool:
    normalized = " ".join(page_text.lower().split())
    if any(keyword in normalized for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS):
        return False
    if section and section.policy == SKIP_SECTION:
        return True
    if is_key_financial_ratios_context(normalized[:1400]) and section and section.policy == PROCESS_ALL:
        return False
    if is_non_comfort_page(normalized):
        return True
    return is_appendix_page(page_text)


def is_appendix_page(page_text: str) -> bool:
    first_lines = [line.strip().lower() for line in page_text.splitlines() if line.strip()][:25]
    first_block = " ".join(first_lines)
    full_block = " ".join(line.strip().lower() for line in page_text.splitlines() if line.strip())
    appendix_heading = any(re.match(r"^(appendix|appendices)\b", line) for line in first_lines)
    appendix_in_page_head = any(re.match(r"^(appendix|appendices)\s+[ivxlcdm0-9]+\b", line) for line in first_lines)
    appendix_title_anywhere = bool(
        re.search(
            r"\bappendix\s+[ivxlcdm0-9]+\b.{0,80}\b("
            r"accountant|summary|constitution|cayman islands|statutory|general information|unaudited pro forma|property valuation|"
            r"documents delivered|documents available"
            r")\b",
            full_block,
        )
    )
    chinese_appendix_heading = any(line.startswith(("附录", "附錄")) for line in first_lines)
    return (
        appendix_heading
        or appendix_in_page_head
        or appendix_title_anywhere
        or chinese_appendix_heading
        or first_block.startswith(APPENDIX_KEYWORDS)
    )


def is_non_comfort_table_region(page_text: str, region_context: str) -> bool:
    normalized_page = " ".join(page_text.lower().split())
    normalized_region = " ".join(region_context.lower().split())
    if any(keyword in normalized_page or keyword in normalized_region for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS):
        return False
    if is_non_comfort_context(normalized_region):
        return True
    page_head = normalized_page[:1200]
    return any(keyword in page_head for keyword in NON_COMFORT_KEYWORDS)


STRONG_NON_COMFORT_PAGE_KEYWORDS = (
    "global offering statistics",
    "history, reorganization and corporate structure",
    "regulatory overview",
    "unaudited pro forma statement of adjusted consolidated net tangible assets",
    "based on an offer price",
    "future plans and use of proceeds",
    "use of proceeds",
    "net proceeds",
    "pricing strategy",
    "structure of the global offering",
    "underwriting",
    "how to apply",
)


def is_non_comfort_page(normalized_page_text: str) -> bool:
    page_head = normalized_page_text[:1800]
    return any(keyword in page_head for keyword in STRONG_NON_COMFORT_PAGE_KEYWORDS)


def should_process_table_region(page_text: str, region: TableRegion, section: SectionState) -> bool:
    if section.policy != PROCESS_ALL:
        return False
    if is_key_financial_ratios_context(region.context):
        return True
    if is_non_comfort_table_region(page_text, region.context):
        return False
    surrounding = get_region_surrounding_text(page_text, region.context)
    return is_financial_table_context(surrounding)


def should_process_line(line_text: str, section: SectionState) -> bool:
    normalized = " ".join(line_text.lower().split())
    if section.policy == PROCESS_ALL:
        return True
    if section.policy == PROCESS_ISSUER_REVENUE_ONLY:
        return is_issuer_revenue_line(normalized)
    if section.policy == PROCESS_DIRECTOR_EMOLUMENTS_ONLY:
        return any(keyword in normalized for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS)
    return False


def is_issuer_revenue_line(normalized_line: str) -> bool:
    issuer_terms = ("our", "we", "company", "group", "the company", "本公司", "我们", "我們", "集团", "集團")
    revenue_terms = ("revenue", "revenues", "total revenue", "收入", "收益", "营业额", "營業額")
    return any(term in normalized_line for term in issuer_terms) and any(term in normalized_line for term in revenue_terms)


FINANCIAL_TABLE_KEYWORDS = (
    "revenue",
    "gross profit",
    "net profit",
    "loss",
    "cost of sales",
    "expenses",
    "ebitda",
    "cash flow",
    "operating activities",
    "investing activities",
    "financing activities",
    "assets",
    "liabilities",
    "equity",
    "borrowings",
    "receivables",
    "payables",
    "inventories",
    "income statement",
    "balance sheet",
    "financial position",
    "financial ratios",
    "key financial ratios",
    "current ratio",
    "aging analysis",
    "ageing analysis",
    "turnover days",
    "trade receivables turnover days",
    "trade and bills payables turnover days",
    "in thousands, except for percentages",
    "in thousand, except for percentages",
    "current assets",
    "current liabilities",
    "non-current assets",
    "non-current liabilities",
    "loss per share",
    "earnings per share",
    "收入",
    "收益",
    "毛利",
    "净利",
    "純利",
    "亏损",
    "虧損",
    "销售成本",
    "銷售成本",
    "开支",
    "開支",
    "现金流",
    "現金流",
    "资产",
    "資產",
    "负债",
    "負債",
    "权益",
    "權益",
)

NON_FINANCIAL_TABLE_KEYWORDS = (
    "users",
    "user",
    "members",
    "employees",
    "headcount",
    "customers",
    "api calls",
    "environmental",
    "environment, social and governance",
    "esg",
    "greenhouse gas",
    "energy consumption",
    "municipal water",
    "wastewater",
    "indicators/unit",
    "kwh",
    "ton/m2",
    "ton/m²",
    "offer price",
    "offer shares",
    "global offering",
    "pricing strategy",
    "price range",
    "pricing tier",
    "monetization method",
    "subscription plan",
    "share capital",
    "ordinary shares",
    "shares held",
    "shares interested",
    "beneficial interests",
    "voting rights",
    "use of proceeds",
    "net proceeds",
    "market capitalization",
    "用户",
    "使用者",
    "成员",
    "员工",
    "雇员",
    "客户",
    "发售",
    "發售",
    "股份",
    "股本",
    "持股",
    "投票权",
    "表决权",
    "所得款项",
    "募资用途",
)

CUSTOMER_SUPPLIER_FINANCIAL_TABLE_KEYWORDS = (
    "revenue contribution",
    "revenue contributions",
    "purchase amount",
    "purchase amounts",
    "purchase contribution",
    "purchase contributions",
    "amount of purchases",
    "amount of sales",
    "sales amount",
    "sales to",
    "purchases from",
    "percentage of total revenue",
    "percentage of total purchases",
    "percentage of our total revenue",
    "percentage of our total purchases",
    "five largest customers",
    "top five customers",
    "five largest suppliers",
    "top five suppliers",
    "major customers",
    "major suppliers",
    "收入贡献",
    "收入貢獻",
    "采购金额",
    "採購金額",
    "购买金额",
    "購買金額",
    "销售金额",
    "銷售金額",
    "占总收入",
    "佔總收入",
    "占总采购",
    "佔總採購",
    "五大客户",
    "五大客戶",
    "五大供应商",
    "五大供應商",
    "主要客户",
    "主要客戶",
    "主要供应商",
    "主要供應商",
)


def is_financial_table_context(context: str) -> bool:
    normalized = " ".join(context.lower().split())
    if is_key_financial_ratios_context(normalized):
        return True
    if is_customer_supplier_financial_table_context(normalized):
        return True
    if is_single_row_financial_table_context(normalized):
        return True
    if any(keyword in normalized for keyword in NON_FINANCIAL_TABLE_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in FINANCIAL_TABLE_KEYWORDS)


def is_single_row_financial_table_context(context: str) -> bool:
    normalized = " ".join(context.lower().split())
    has_aging = "aging analysis" in normalized or "ageing analysis" in normalized
    has_turnover_days = "turnover days" in normalized or ("turnover" in normalized and "days" in normalized)
    has_financial_account = any(
        account in normalized
        for account in (
            "trade receivables",
            "trade and bills payables",
            "receivables",
            "payables",
        )
    )
    has_table_signal = "(us$ in thousands)" in normalized or "(days)" in normalized or "as of december 31" in normalized
    return (has_aging or has_turnover_days) and has_financial_account and has_table_signal


def is_key_financial_ratios_context(context: str) -> bool:
    normalized = " ".join(context.lower().split())
    has_ratio_label = any(
        label in normalized
        for label in (
            "key financial ratios",
            "key income statement ratio",
            "key balance sheet ratio",
        )
    )
    has_ratio_rows = any(
        label in normalized
        for label in (
            "revenue growth",
            "gross margin",
            "net loss margin",
            "adjusted net loss margin",
            "current ratio",
        )
    )
    return has_ratio_label and has_ratio_rows


def is_customer_supplier_financial_table_context(normalized: str) -> bool:
    has_customer_or_supplier = any(term in normalized for term in ("customer", "supplier", "客户", "客戶", "供应商", "供應商"))
    has_financial_column = any(keyword in normalized for keyword in CUSTOMER_SUPPLIER_FINANCIAL_TABLE_KEYWORDS)
    return has_customer_or_supplier and has_financial_column


def get_region_surrounding_text(page_text: str, region_context: str) -> str:
    return region_context


def merge_table_regions(fitz_module, regions: list[TableRegion]) -> list[TableRegion]:
    if not regions:
        return []

    sorted_regions = sorted(regions, key=lambda region: (region.rect.y0, region.rect.x0))
    merged: list[TableRegion] = []

    for region in sorted_regions:
        if not merged:
            merged.append(region)
            continue

        previous = merged[-1]
        if should_merge_table_regions(previous, region):
            merged.append(merge_two_table_regions(fitz_module, previous, region))
            del merged[-2]
        else:
            merged.append(region)

    return merged


def should_merge_table_regions(first: TableRegion, second: TableRegion) -> bool:
    vertical_gap = second.rect.y0 - first.rect.y1
    x_overlap = min(first.rect.x1, second.rect.x1) - max(first.rect.x0, second.rect.x0)
    min_width = min(first.rect.x1 - first.rect.x0, second.rect.x1 - second.rect.x0)
    similar_numeric_columns = x_overlap >= min_width * 0.45
    return 0 <= vertical_gap <= 140 and similar_numeric_columns


def merge_two_table_regions(fitz_module, first: TableRegion, second: TableRegion) -> TableRegion:
    rect = fitz_module.Rect(
        min(first.rect.x0, second.rect.x0),
        min(first.rect.y0, second.rect.y0),
        max(first.rect.x1, second.rect.x1),
        max(first.rect.y1, second.rect.y1),
    )
    context = compact_context(f"{first.context} | {second.context}", limit=220)
    return TableRegion(rect=rect, row_count=first.row_count + second.row_count, context=context)


def group_words_by_line(words: list[tuple]) -> list[list[tuple]]:
    sorted_words = sorted(words, key=lambda word: (word[1], word[0]))
    lines: list[list[tuple]] = []

    for word in sorted_words:
        if not lines:
            lines.append([word])
            continue

        current_mid_y = (word[1] + word[3]) / 2
        previous_mid_y = sum((item[1] + item[3]) / 2 for item in lines[-1]) / len(lines[-1])
        if abs(current_mid_y - previous_mid_y) < 4.0:
            lines[-1].append(word)
        else:
            lines.append([word])

    for line in lines:
        line.sort(key=lambda word: word[0])

    return lines


def join_words(words: list[tuple]) -> str:
    return " ".join(str(word[4]) for word in words)


TABLE_NUMBER_PATTERN = re.compile(
    r"""^\(?[–—-]?\$?(?:HK\$|RMB|US\$|USD|HKD|CNY)?\s*\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\)?[.,]?$""",
    re.IGNORECASE | re.VERBOSE,
)


def detect_table_numeric_regions(fitz_module, lines: list[list[tuple]]) -> list[TableRegion]:
    candidates = []

    for line_index, line in enumerate(lines):
        data_cell_words = [word for word in line if is_table_data_cell_word(str(word[4]))]
        numeric_words = [word for word in line if is_table_number_word(str(word[4]))]
        if len(data_cell_words) < 2:
            continue
        if is_header_numeric_line(numeric_words):
            continue
        if not is_table_candidate_line(line_index, line, data_cell_words, numeric_words, lines):
            continue

        x_values = [word[0] for word in data_cell_words]
        if max(x_values) - min(x_values) < 45:
            continue

        candidates.append((line_index, line, data_cell_words))

    regions: list[TableRegion] = []
    current: list[tuple[int, list[tuple], list[tuple]]] = []

    for candidate in candidates:
        if not current:
            current = [candidate]
            continue

        previous_y = line_mid_y(current[-1][1])
        current_y = line_mid_y(candidate[1])
        if current_y - previous_y <= 95:
            current.append(candidate)
        else:
            append_table_region(fitz_module, regions, current, lines)
            current = [candidate]

    append_table_region(fitz_module, regions, current, lines)
    return extend_table_regions_with_sparse_financial_rows(fitz_module, regions, lines)


def append_table_region(
    fitz_module,
    regions: list[TableRegion],
    rows: list[tuple[int, list[tuple], list[tuple]]],
    all_lines: list[list[tuple]],
) -> None:
    if not rows:
        return
    context = build_table_context(rows, all_lines)
    is_single_row_financial_table = is_single_row_financial_table_context(context)
    min_rows = 1 if is_single_row_financial_table else 3
    if len(rows) < min_rows:
        return
    min_repeated_columns = 2 if is_customer_supplier_financial_table_context(" ".join(context.lower().split())) else 3
    if not is_single_row_financial_table and not has_repeated_data_columns(rows, min_repeated_columns=min_repeated_columns):
        return

    data_cell_words = [word for _, _, row_data_cell_words in rows for word in row_data_cell_words]
    x0 = min(word[0] for word in data_cell_words) - 2.0
    y0 = min(min(word[1] for word in line) for _, line, _ in rows) - 2.0
    x1 = max(word[2] for word in data_cell_words) + 2.0
    y1 = max(max(word[3] for word in line) for _, line, _ in rows) + 2.0

    regions.append(
        TableRegion(
            rect=fitz_module.Rect(x0, y0, x1, y1),
            row_count=len(rows),
            context=context,
        )
    )


def build_table_context(rows: list[tuple[int, list[tuple], list[tuple]]], all_lines: list[list[tuple]]) -> str:
    first_index = rows[0][0]
    last_index = rows[-1][0]
    first_y = line_mid_y(rows[0][1])
    last_y = line_mid_y(rows[-1][1])

    context_lines: list[str] = []
    for index, line in enumerate(all_lines):
        y = line_mid_y(line)
        is_near_header = index < first_index and first_y - 165 <= y < first_y
        is_table_body = first_index <= index <= last_index and first_y <= y <= last_y + 1
        if is_near_header or is_table_body:
            text = compact_context(join_words(line), limit=100)
            if text:
                context_lines.append(text)

    return compact_context(" | ".join(context_lines), limit=900)


def extend_table_regions_with_sparse_financial_rows(
    fitz_module,
    regions: list[TableRegion],
    lines: list[list[tuple]],
) -> list[TableRegion]:
    extended: list[TableRegion] = []
    for region in regions:
        sparse_rows = find_following_sparse_financial_rows(region, lines)
        if not sparse_rows:
            extended.append(region)
            continue

        data_cell_words = [
            word
            for _, line in sparse_rows
            for word in line
            if is_table_data_cell_word(str(word[4]))
        ]
        rect = fitz_module.Rect(
            min(region.rect.x0, min(word[0] for word in data_cell_words) - 2.0),
            region.rect.y0,
            max(region.rect.x1, max(word[2] for word in data_cell_words) + 2.0),
            max(max(word[3] for _, line in sparse_rows for word in line) + 2.0, region.rect.y1),
        )
        extra_context = " | ".join(compact_context(join_words(line), limit=100) for _, line in sparse_rows)
        extended.append(
            TableRegion(
                rect=rect,
                row_count=region.row_count + len(sparse_rows),
                context=compact_context(f"{region.context} | {extra_context}", limit=900),
            )
        )
    return extended


def find_following_sparse_financial_rows(region: TableRegion, lines: list[list[tuple]]) -> list[tuple[int, list[tuple]]]:
    sparse_rows: list[tuple[int, list[tuple]]] = []
    label_window: list[str] = []
    for index, line in enumerate(lines):
        y = line_mid_y(line)
        if y <= region.rect.y1 or y - region.rect.y1 > 135:
            continue
        text = join_words(line)
        if is_page_footer_line(text):
            continue
        label_window.append(text.lower())
        nearby_text = " ".join(label_window[-8:])
        data_cell_words = [word for word in line if is_table_data_cell_word(str(word[4]))]
        if len(data_cell_words) < 2:
            continue
        if not is_sparse_financial_continuation_context(nearby_text):
            continue
        if not row_overlaps_region_columns(region, data_cell_words):
            continue
        sparse_rows.append((index, line))
    return sparse_rows


def is_sparse_financial_continuation_context(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "loss per share",
            "earnings per share",
            "basic and diluted",
            "for loss for the",
            "for profit for the",
            "turnover days",
        )
    )


def row_overlaps_region_columns(region: TableRegion, data_cell_words: list[tuple]) -> bool:
    inside = [
        word
        for word in data_cell_words
        if region.rect.x0 - 18 <= (word[0] + word[2]) / 2 <= region.rect.x1 + 18
    ]
    return len(inside) >= max(2, len(data_cell_words) - 1)


def is_page_footer_line(text: str) -> bool:
    return bool(re.fullmatch(r"[–—-]?\s*\d+\s*[–—-]?", text.strip()))


def is_table_candidate_line(
    line_index: int,
    line: list[tuple],
    data_cell_words: list[tuple],
    numeric_words: list[tuple],
    all_lines: list[list[tuple]],
) -> bool:
    local_context = build_local_table_context(line_index, all_lines)
    normalized_context = " ".join(local_context.lower().split())
    has_financial_header = is_financial_table_context(normalized_context)
    has_customer_supplier_header = is_customer_supplier_financial_table_context(normalized_context)
    has_table_ruling_or_leaders = line_has_dot_leader(line) or nearby_line_has_ruling(line_index, all_lines)
    has_placeholder_or_dash = any(
        is_dash_word(str(word[4])) or is_placeholder_word(str(word[4])) or is_na_word(str(word[4]))
        for word in data_cell_words
    )

    word_count = max(len(line), 1)
    data_density = len(data_cell_words) / word_count
    numeric_density = len(numeric_words) / word_count

    x_values = [word[0] for word in data_cell_words]
    has_spread_columns = max(x_values) - min(x_values) >= 45 if x_values else False
    if not has_spread_columns:
        return False

    if has_customer_supplier_header:
        return True

    # A narrative sentence immediately below a financial table may include
    # several currency amounts. It should be handled as line-level text, not
    # merged into the table's numeric-area rectangle.
    looks_like_prose = word_count >= 10 and data_density < 0.35 and not line_has_dot_leader(line)
    if looks_like_prose:
        return False

    if data_density >= 0.35:
        return True

    if len(data_cell_words) >= 4 and (has_financial_header or has_table_ruling_or_leaders or has_placeholder_or_dash):
        return True

    if len(data_cell_words) >= 3 and has_financial_header and has_placeholder_or_dash:
        return True

    return has_financial_header and len(data_cell_words) >= 3


def build_local_table_context(line_index: int, all_lines: list[list[tuple]], lookback: int = 8) -> str:
    start = max(0, line_index - lookback)
    context_lines = [compact_context(join_words(line), limit=100) for line in all_lines[start : line_index + 1]]
    return " | ".join(line for line in context_lines if line)


def line_has_dot_leader(line: list[tuple]) -> bool:
    return any(re.fullmatch(r"[.·]{2,}", str(word[4]).strip()) for word in line)


def nearby_line_has_ruling(line_index: int, all_lines: list[list[tuple]], lookaround: int = 2) -> bool:
    start = max(0, line_index - lookaround)
    end = min(len(all_lines), line_index + lookaround + 1)
    for line in all_lines[start:end]:
        if sum(1 for word in line if is_rule_like_word(str(word[4]))) >= 2:
            return True
    return False


def is_rule_like_word(text: str) -> bool:
    cleaned = text.strip()
    return bool(re.fullmatch(r"[_=\-–—]{2,}", cleaned))


def has_repeated_data_columns(
    rows: list[tuple[int, list[tuple], list[tuple]]],
    *,
    min_repeated_columns: int = 3,
) -> bool:
    clusters: list[dict] = []

    for row_index, (_, _, data_cell_words) in enumerate(rows):
        for word in data_cell_words:
            x = word[0]
            for cluster in clusters:
                if abs(cluster["x"] - x) <= 12.0:
                    cluster["xs"].append(x)
                    cluster["rows"].add(row_index)
                    cluster["x"] = sum(cluster["xs"]) / len(cluster["xs"])
                    break
            else:
                clusters.append({"x": x, "xs": [x], "rows": {row_index}})

    min_row_support = min(3, len(rows))
    repeated_columns = [cluster for cluster in clusters if len(cluster["rows"]) >= min_row_support]
    return len(repeated_columns) >= min_repeated_columns


def is_table_data_cell_word(text: str) -> bool:
    return is_table_number_word(text) or is_dash_word(text) or is_placeholder_word(text) or is_na_word(text)


def is_table_number_word(text: str) -> bool:
    cleaned = text.strip()
    if is_dash_word(cleaned):
        return False
    return bool(TABLE_NUMBER_PATTERN.match(cleaned))


def is_dash_word(text: str) -> bool:
    return text.strip() in {"–", "-", "—"}


def is_placeholder_word(text: str) -> bool:
    cleaned = text.strip()
    if re.fullmatch(r"\[\s*(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?|[*·•.-]+)\s*\]", cleaned):
        return True
    return cleaned in {"[*]", "[·]", "[•]", "[--]", "[-]"}


def is_na_word(text: str) -> bool:
    return text.strip().lower().rstrip(".,") in {"n/a", "na"}


def is_header_numeric_line(numeric_words: list[tuple]) -> bool:
    texts = [str(word[4]).strip(".,()") for word in numeric_words]
    if not texts:
        return False
    year_count = sum(1 for text in texts if re.fullmatch(r"(19|20)\d{2}", text))
    small_day_count = sum(1 for text in texts if text.isdigit() and 1 <= int(text) <= 31)
    return (
        year_count >= max(2, len(texts) - 1)
        or (year_count >= 1 and small_day_count >= 1)
        or small_day_count == len(texts)
    )


def line_mid_y(line: list[tuple]) -> float:
    return sum((word[1] + word[3]) / 2 for word in line) / len(line)


def rectangles_for_hit(fitz_module, words: list[tuple], line_text: str, start: int, end: int):
    spans = word_spans(words)
    rects = []

    for word, word_start, word_end in spans:
        if word_end <= start or word_start >= end:
            continue

        rect = partial_word_rect(fitz_module, word, word_start, word_end, start, end)
        rect.x0 -= 1.0
        rect.y0 -= 0.8
        rect.x1 += 1.0
        rect.y1 += 0.8
        rects.append(rect)

    return merge_rects_on_same_line(fitz_module, rects)


def rect_center_inside(rect, container) -> bool:
    center_x = (rect.x0 + rect.x1) / 2
    center_y = (rect.y0 + rect.y1) / 2
    return container.x0 <= center_x <= container.x1 and container.y0 <= center_y <= container.y1


def partial_word_rect(fitz_module, word: tuple, word_start: int, word_end: int, hit_start: int, hit_end: int):
    text = str(word[4])
    text_length = max(len(text), 1)
    overlap_start = max(hit_start, word_start) - word_start
    overlap_end = min(hit_end, word_end) - word_start

    x0, y0, x1, y1 = word[:4]
    width = x1 - x0
    clipped_x0 = x0 + width * (overlap_start / text_length)
    clipped_x1 = x0 + width * (overlap_end / text_length)

    return fitz_module.Rect(clipped_x0, y0, clipped_x1, y1)


def word_spans(words: list[tuple]) -> list[tuple[tuple, int, int]]:
    spans = []
    cursor = 0

    for index, word in enumerate(words):
        text = str(word[4])
        start = cursor
        end = start + len(text)
        spans.append((word, start, end))
        cursor = end + 1

    return spans


def merge_rects_on_same_line(fitz_module, rects):
    if not rects:
        return []

    merged = [rects[0]]
    for rect in rects[1:]:
        previous = merged[-1]
        same_line = abs(rect.y0 - previous.y0) < 3.0 and abs(rect.y1 - previous.y1) < 3.0
        close_gap = rect.x0 - previous.x1 < 6.0
        if same_line and close_gap:
            merged[-1] = fitz_module.Rect(
                min(previous.x0, rect.x0),
                min(previous.y0, rect.y0),
                max(previous.x1, rect.x1),
                max(previous.y1, rect.y1),
            )
        else:
            merged.append(rect)

    return merged


def compact_context(text: str, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def write_findings_csv(csv_path: Path, findings: list[Finding]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["page", "text", "reason", "context"])
        writer.writeheader()
        for finding in findings:
            writer.writerow(
                {
                    "page": finding.page,
                    "text": finding.text,
                    "reason": finding.reason,
                    "context": finding.context,
                }
            )
