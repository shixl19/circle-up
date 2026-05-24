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
    ("risk factors", "risk factors"),
    ("business", "business"),
    ("financial information", "financial information"),
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
    "relationship with our controlling shareholders",
    "connected transactions",
    "share capital",
    "substantial shareholders",
    "cornerstone investors",
    "future plans and use of proceeds",
    "underwriting",
    "structure of the global offering",
    "how to apply",
    "appendix",
    "附录",
    "附錄",
)


def update_section_state(current: SectionState, page_text: str) -> SectionState:
    headings = get_page_heading_candidates(page_text)
    if not headings:
        return current

    joined = " ".join(headings)
    for pattern, section_name in CORE_SECTION_PATTERNS:
        if heading_contains(joined, pattern):
            return SectionState(section_name, PROCESS_ALL)
    if any(heading_contains(joined, pattern) for pattern in INDUSTRY_SECTION_PATTERNS):
        return SectionState("industry overview", PROCESS_ISSUER_REVENUE_ONLY)
    if any(heading_contains(joined, pattern) for pattern in DIRECTOR_SECTION_PATTERNS):
        return SectionState("directors/statutory", PROCESS_DIRECTOR_EMOLUMENTS_ONLY)
    if any(heading_contains(joined, pattern) for pattern in STOP_SECTION_PATTERNS):
        return SectionState("other", SKIP_SECTION)
    return current


def get_page_heading_candidates(page_text: str) -> list[str]:
    lines = [line.strip().lower() for line in page_text.splitlines() if line.strip()]
    candidates: list[str] = []
    for line in lines[:18]:
        cleaned = re.sub(r"\s+", " ", line)
        if len(cleaned) <= 90:
            candidates.append(cleaned)
    return candidates


def heading_contains(text: str, pattern: str) -> bool:
    return pattern.lower() in text.lower()


def should_skip_page(page_text: str, section: SectionState | None = None) -> bool:
    normalized = " ".join(page_text.lower().split())
    if any(keyword in normalized for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS):
        return False
    if is_non_comfort_page(normalized):
        return True
    if section and section.policy == SKIP_SECTION:
        return True
    return is_appendix_page(page_text)


def is_appendix_page(page_text: str) -> bool:
    first_lines = [line.strip().lower() for line in page_text.splitlines() if line.strip()][:8]
    first_block = " ".join(first_lines)
    appendix_heading = any(re.match(r"^(appendix|appendices)\b", line) for line in first_lines)
    chinese_appendix_heading = any(line.startswith(("附录", "附錄")) for line in first_lines)
    return appendix_heading or chinese_appendix_heading or first_block.startswith(APPENDIX_KEYWORDS)


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
    "future plans and use of proceeds",
    "use of proceeds",
    "pricing strategy",
    "structure of the global offering",
    "underwriting",
    "how to apply",
    "offer price",
    "offer shares",
    "offer size adjustment option",
    "over-allotment option",
    "share capital",
    "substantial shareholders",
    "beneficial interests",
    "voting rights",
)


def is_non_comfort_page(normalized_page_text: str) -> bool:
    page_head = normalized_page_text[:1800]
    return any(keyword in page_head for keyword in STRONG_NON_COMFORT_PAGE_KEYWORDS)


def should_process_table_region(page_text: str, region: TableRegion, section: SectionState) -> bool:
    if section.policy != PROCESS_ALL:
        return False
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
    if is_customer_supplier_financial_table_context(normalized):
        return True
    if any(keyword in normalized for keyword in NON_FINANCIAL_TABLE_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in FINANCIAL_TABLE_KEYWORDS)


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
    return regions


def append_table_region(
    fitz_module,
    regions: list[TableRegion],
    rows: list[tuple[int, list[tuple], list[tuple]]],
    all_lines: list[list[tuple]],
) -> None:
    if len(rows) < 3:
        return
    context = build_table_context(rows, all_lines)
    min_repeated_columns = 2 if is_customer_supplier_financial_table_context(" ".join(context.lower().split())) else 3
    if not has_repeated_data_columns(rows, min_repeated_columns=min_repeated_columns):
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
        is_near_header = index < first_index and first_y - 115 <= y < first_y
        is_table_body = first_index <= index <= last_index and first_y <= y <= last_y + 1
        if is_near_header or is_table_body:
            text = compact_context(join_words(line), limit=100)
            if text:
                context_lines.append(text)

    return compact_context(" | ".join(context_lines), limit=420)


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
    return is_table_number_word(text) or is_dash_word(text) or is_placeholder_word(text)


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
