from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import re

from .detector import DIRECTOR_EMOLUMENTS_KEYWORDS, NON_COMFORT_KEYWORDS, find_numeric_hits, is_non_comfort_context


@dataclass(frozen=True)
class Finding:
    page: int
    text: str
    reason: str
    context: str


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

    for page_index, page in enumerate(document):
        page_text = page.get_text("text")
        if should_skip_page(page_text):
            continue

        words = page.get_text("words")
        lines = group_words_by_line(words)
        numeric_regions = detect_table_numeric_regions(fitz, lines) if table_regions else []
        numeric_regions = [
            region
            for region in numeric_regions
            if not is_non_comfort_table_region(page_text, region.context)
        ]

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


def should_skip_page(page_text: str) -> bool:
    normalized = " ".join(page_text.lower().split())
    if any(keyword in normalized for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS):
        return False
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

    for line in lines:
        data_cell_words = [word for word in line if is_table_data_cell_word(str(word[4]))]
        numeric_words = [word for word in line if is_table_number_word(str(word[4]))]
        if len(data_cell_words) < 2:
            continue
        numeric_density = len(numeric_words) / max(len(line), 1)
        cell_density = len(data_cell_words) / max(len(line), 1)
        if numeric_density < 0.35 and cell_density < 0.55:
            continue
        if is_header_numeric_line(numeric_words):
            continue

        x_values = [word[0] for word in data_cell_words]
        if max(x_values) - min(x_values) < 45:
            continue

        candidates.append((line, data_cell_words))

    regions: list[TableRegion] = []
    current: list[tuple[list[tuple], list[tuple]]] = []

    for candidate in candidates:
        if not current:
            current = [candidate]
            continue

        previous_y = line_mid_y(current[-1][0])
        current_y = line_mid_y(candidate[0])
        if current_y - previous_y <= 68:
            current.append(candidate)
        else:
            append_table_region(fitz_module, regions, current)
            current = [candidate]

    append_table_region(fitz_module, regions, current)
    return regions


def append_table_region(fitz_module, regions: list[TableRegion], rows: list[tuple[list[tuple], list[tuple]]]) -> None:
    if len(rows) < 3:
        return
    if not has_repeated_data_columns(rows):
        return

    data_cell_words = [word for _, row_data_cell_words in rows for word in row_data_cell_words]
    x0 = min(word[0] for word in data_cell_words) - 2.0
    y0 = min(min(word[1] for word in line) for line, _ in rows) - 2.0
    x1 = max(word[2] for word in data_cell_words) + 2.0
    y1 = max(max(word[3] for word in line) for line, _ in rows) + 2.0

    contexts = [compact_context(join_words(line), limit=80) for line, _ in rows[:3]]
    regions.append(
        TableRegion(
            rect=fitz_module.Rect(x0, y0, x1, y1),
            row_count=len(rows),
            context=" | ".join(contexts),
        )
    )


def has_repeated_data_columns(rows: list[tuple[list[tuple], list[tuple]]]) -> bool:
    clusters: list[dict] = []

    for row_index, (_, data_cell_words) in enumerate(rows):
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
    return len(repeated_columns) >= 3


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
