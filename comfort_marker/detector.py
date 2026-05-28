from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


FINANCIAL_KEYWORDS = (
    "revenue",
    "turnover",
    "gross profit",
    "net profit",
    "profit for the year",
    "profit for the period",
    "loss for the year",
    "loss for the period",
    "adjusted profit",
    "adjusted net profit",
    "ebitda",
    "adjusted ebitda",
    "margin",
    "cost of sales",
    "selling expenses",
    "administrative expenses",
    "research and development",
    "r&d",
    "finance costs",
    "income tax",
    "cash flow",
    "operating cash",
    "working capital",
    "capital expenditure",
    "capex",
    "assets",
    "liabilities",
    "equity",
    "borrowings",
    "inventories",
    "inventory turnover",
    "turnover days",
    "receivables turnover",
    "payables turnover",
    "trade receivables",
    "trade payables",
    "earnings per share",
    "eps",
    "收入",
    "收益",
    "营业额",
    "毛利",
    "净利",
    "纯利",
    "亏损",
    "经调整",
    "毛利率",
    "净利率",
    "销售成本",
    "研发",
    "现金流",
    "营运资金",
    "资本开支",
    "资产",
    "负债",
    "权益",
    "借款",
    "存货",
    "应收",
    "应付",
    "每股",
)

DIRECTOR_EMOLUMENTS_KEYWORDS = (
    "director emoluments",
    "directors' emoluments",
    "directors’ emoluments",
    "director remuneration",
    "directors' remuneration",
    "directors’ remuneration",
    "董事薪酬",
    "董事酬金",
    "董事袍金",
)

MARKET_DATA_KEYWORDS = (
    "market size",
    "market share",
    "market ranking",
    "market position",
    "market growth",
    "market is projected",
    "market is expected",
    "industry size",
    "industry growth",
    "global market",
    "addressable market",
    "gdp",
    "cagr",
    "compound annual growth rate",
    "frost & sullivan",
    "idc",
    "iresearch",
    "艾瑞",
    "弗若斯特",
    "沙利文",
    "市场规模",
    "市场份额",
    "市场排名",
    "市场地位",
    "行业规模",
    "行业增长",
    "行业增速",
    "复合年增长率",
    "国内生产总值",
)

NON_COMFORT_KEYWORDS = (
    "use of proceeds",
    "future plans and use of proceeds",
    "net proceeds",
    "net ipo proceeds",
    "ipo proceeds",
    "gross proceeds",
    "gross ipo proceeds",
    "proceeds from the global offering",
    "proceeds from the offering",
    "allocation of proceeds",
    "global offering",
    "offer shares",
    "offer price",
    "public offer",
    "international offering",
    "placing shares",
    "subscription shares",
    "issued share capital",
    "authorised share capital",
    "authorized share capital",
    "share capital",
    "capitalisation",
    "capitalization",
    "market capitalisation",
    "market capitalization",
    "beneficial interests",
    "voting rights",
    "shareholding",
    "shareholder",
    "shareholders",
    "ordinary shares",
    "class a ordinary shares",
    "class b ordinary shares",
    "shares held",
    "shares interested",
    "募资用途",
    "募集资金用途",
    "所得款项用途",
    "所得款项净额",
    "所得款项总额",
    "全球发售",
    "发售股份",
    "发行股份",
    "发售价",
    "公开发售",
    "国际发售",
    "配售股份",
    "认购股份",
    "股本",
    "已发行股本",
    "法定股本",
    "市值",
    "持股",
    "股权",
    "股东",
    "投票权",
    "表决权",
    "普通股",
)

NON_FINANCIAL_OPERATING_KEYWORDS = (
    "users",
    "user",
    "members",
    "member",
    "employees",
    "employee",
    "headcount",
    "r&d team",
    "research and development team",
    "monthly active users",
    "active users",
    "paying users",
    "customers",
    "api calls",
    "用户",
    "成员",
    "雇员",
    "员工",
    "人数",
    "客户",
)

NON_FINANCIAL_PERCENT_CONTEXT_KEYWORDS = (
    "users",
    "user",
    "members",
    "member",
    "employees",
    "employee",
    "personnel",
    "headcount",
    "api calls",
    "用户",
    "成员",
    "雇员",
    "员工",
    "人数",
)

ENVIRONMENTAL_DATA_KEYWORDS = (
    "environmental",
    "environment, social and governance",
    "esg",
    "greenhouse gas",
    "energy consumption",
    "municipal water",
    "wastewater",
    "carbon dioxide",
    "kwh",
    "ton/m2",
    "ton/m²",
)

PERIOD_KEYWORDS = (
    "year ended",
    "years ended",
    "period ended",
    "track record period",
    "fy",
    "fiscal year",
    "年度",
    "截至",
    "往绩记录期间",
)

MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
)

NUMBER_PATTERN = re.compile(
    r"""
    (?P<prefix>HK\$|RMB|US\$|USD|HKD|CNY|\$|人民币|港元|美元)?
    \s*
    (?P<number>
        \(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?
        |
        \(?\d+(?:\.\d+)?\)?
    )
    \s*
    (?P<suffix>%|percent|percentage\ points?|bps|basis\ points?|days?|million|billion|trillion|thousand|m\b|bn\b|tn\b|万|億|亿|千)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

DATE_ONLY_PATTERN = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class NumericHit:
    text: str
    start: int
    end: int
    reason: str


def find_numeric_hits(text: str, *, mode: str = "conservative") -> list[NumericHit]:
    """Return numeric spans that likely need accountant comfort."""
    if mode not in {"conservative", "broad"}:
        raise ValueError("mode must be 'conservative' or 'broad'")

    hits: list[NumericHit] = []
    normalized = " ".join(text.lower().split())
    has_financial_context = any(keyword in normalized for keyword in FINANCIAL_KEYWORDS)
    has_period_context = any(keyword in normalized for keyword in PERIOD_KEYWORDS)
    has_market_data_context = any(keyword in normalized for keyword in MARKET_DATA_KEYWORDS)
    has_environmental_data_context = any(keyword in normalized for keyword in ENVIRONMENTAL_DATA_KEYWORDS)
    has_non_comfort_context = is_non_comfort_context(normalized)
    has_director_emoluments_context = any(keyword in normalized for keyword in DIRECTOR_EMOLUMENTS_KEYWORDS)
    has_non_financial_operating_context = is_non_financial_operating_context(normalized)
    has_non_financial_percent_context = is_non_financial_percent_context(normalized)

    for match in NUMBER_PATTERN.finditer(text):
        raw = match.group(0)
        value = raw.strip()
        if not value:
            continue
        if is_likely_date_component(text, match.start(), match.end(), value):
            continue

        reason = classify_number(
            value,
            has_financial_context=has_financial_context,
            has_period_context=has_period_context,
            has_market_data_context=has_market_data_context,
            has_environmental_data_context=has_environmental_data_context,
            has_non_comfort_context=has_non_comfort_context,
            has_director_emoluments_context=has_director_emoluments_context,
            has_non_financial_operating_context=has_non_financial_operating_context,
            has_non_financial_percent_context=has_non_financial_percent_context,
            mode=mode,
        )
        if reason:
            hits.append(NumericHit(value, match.start(), match.end(), reason))

    return merge_overlapping_hits(hits)


def classify_number(
    value: str,
    *,
    has_financial_context: bool,
    has_period_context: bool,
    has_market_data_context: bool,
    has_environmental_data_context: bool,
    has_non_comfort_context: bool,
    has_director_emoluments_context: bool,
    has_non_financial_operating_context: bool,
    has_non_financial_percent_context: bool,
    mode: str,
) -> str | None:
    compact = value.replace(" ", "").lower()
    has_currency = any(token in compact for token in ("hk$", "rmb", "us$", "usd", "hkd", "cny", "$", "人民币", "港元", "美元"))
    has_unit = any(token in compact for token in ("million", "billion", "trillion", "thousand", "bn", "tn", "万", "億", "亿", "千"))
    has_percent = "%" in compact or "percent" in compact or "basis" in compact or compact.endswith("bps")
    has_day_metric = compact.endswith("day") or compact.endswith("days")
    is_year = bool(DATE_ONLY_PATTERN.match(compact))

    if is_year:
        return None
    if has_non_comfort_context and not has_director_emoluments_context:
        return None
    if has_percent and has_non_financial_percent_context:
        return None
    if has_non_financial_operating_context and not has_currency and not has_percent and not has_day_metric:
        return None
    if has_environmental_data_context:
        return None
    if has_market_data_context:
        return None
    if has_currency:
        return "currency amount"
    if has_percent:
        return "percentage"
    if has_day_metric and has_financial_context:
        return "financial operating metric"
    if has_unit and has_financial_context:
        return "financial amount with unit"
    if has_financial_context:
        return "number in financial context"
    if mode == "broad" and not is_year:
        return "broad numeric capture"
    return None


def is_non_comfort_context(normalized_text: str) -> bool:
    return any(keyword in normalized_text for keyword in NON_COMFORT_KEYWORDS)


def is_non_financial_operating_context(normalized_text: str) -> bool:
    return any(keyword in normalized_text for keyword in NON_FINANCIAL_OPERATING_KEYWORDS)


def is_non_financial_percent_context(normalized_text: str) -> bool:
    return any(keyword in normalized_text for keyword in NON_FINANCIAL_PERCENT_CONTEXT_KEYWORDS)


def is_likely_date_component(text: str, start: int, end: int, value: str) -> bool:
    compact_value = value.strip("(), ")
    if not compact_value.isdigit():
        return False

    left = text[max(0, start - 24) : start].lower()
    right = text[end : min(len(text), end + 12)].lower()
    near_month = any(month in left for month in MONTH_NAMES)
    followed_by_year = bool(re.match(r"\s*,?\s*(19|20)\d{2}\b", right))

    if near_month and (1 <= int(compact_value) <= 31 or DATE_ONLY_PATTERN.match(compact_value)):
        return True
    if 1 <= int(compact_value) <= 31 and followed_by_year:
        return True
    return False


def merge_overlapping_hits(hits: Iterable[NumericHit]) -> list[NumericHit]:
    sorted_hits = sorted(hits, key=lambda hit: (hit.start, hit.end))
    merged: list[NumericHit] = []

    for hit in sorted_hits:
        if not merged or hit.start >= merged[-1].end:
            merged.append(hit)
            continue

        previous = merged[-1]
        if hit.end > previous.end:
            merged[-1] = NumericHit(
                text=previous.text,
                start=previous.start,
                end=hit.end,
                reason=previous.reason,
            )

    return merged
