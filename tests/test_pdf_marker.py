import unittest

import fitz

from comfort_marker.pdf_marker import (
    SectionState,
    PROCESS_ALL,
    PROCESS_DIRECTOR_EMOLUMENTS_ONLY,
    PROCESS_ISSUER_REVENUE_ONLY,
    SKIP_SECTION,
    TableRegion,
    detect_table_numeric_regions,
    is_appendix_page,
    is_financial_table_context,
    is_non_comfort_page,
    is_dash_word,
    is_non_comfort_table_region,
    is_placeholder_word,
    is_table_data_cell_word,
    merge_table_regions,
    should_process_line,
    should_process_table_region,
    should_skip_page,
    update_section_state,
)


def word(x0, y0, text, width=20):
    return (x0, y0, x0 + width, y0 + 8, text, 0, 0, 0)


class PdfMarkerTests(unittest.TestCase):
    def test_table_regions_include_dashes_and_placeholders(self):
        lines = [
            [
                word(80, 100, "Revenue", 45),
                word(200, 100, "-"),
                word(240, 100, "[768]", 28),
                word(280, 100, "[*]"),
                word(320, 100, "1,000", 30),
            ],
            [
                word(80, 115, "Cost", 25),
                word(200, 115, "(123)", 30),
                word(240, 115, "–"),
                word(280, 115, "[·]"),
                word(320, 115, "2,000", 30),
            ],
            [
                word(80, 130, "Total", 28),
                word(200, 130, "0"),
                word(240, 130, "-"),
                word(280, 130, "[--]", 25),
                word(320, 130, "3,000", 30),
            ],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertLessEqual(regions[0].rect.x0, 198)
        self.assertGreaterEqual(regions[0].rect.x1, 348)

    def test_data_cell_classification(self):
        for text in ["-", "–", "—"]:
            self.assertTrue(is_dash_word(text))
            self.assertTrue(is_table_data_cell_word(text))

        for text in ["[768]", "[*]", "[·]", "[--]"]:
            self.assertTrue(is_placeholder_word(text))
            self.assertTrue(is_table_data_cell_word(text))

    def test_appendix_pages_are_skipped_except_director_emoluments(self):
        self.assertTrue(is_appendix_page("APPENDIX IV\nSTATUTORY AND GENERAL INFORMATION\n"))
        self.assertTrue(should_skip_page("APPENDIX IV\nSTATUTORY AND GENERAL INFORMATION\n"))
        self.assertFalse(
            should_skip_page("APPENDIX IV\nSTATUTORY AND GENERAL INFORMATION\nDirectors' emoluments were US$1.2 million.")
        )

    def test_non_comfort_table_region_filter(self):
        use_of_proceeds_page = "Future Plans and Use of Proceeds\nWe expect to allocate the net proceeds as follows."
        share_capital_context = "Issued share capital 25,389,220 Offer Shares HK$151.0 per Share"
        financial_context = "Revenue – – 3,460 100.0 30,523 100.0"

        self.assertTrue(is_non_comfort_table_region(use_of_proceeds_page, financial_context))
        self.assertTrue(is_non_comfort_table_region("", share_capital_context))
        self.assertFalse(is_non_comfort_table_region("Financial Information", financial_context))

    def test_section_state_whitelist(self):
        current = SectionState("unknown", SKIP_SECTION)

        self.assertEqual(update_section_state(current, "SUMMARY\nOverview").policy, PROCESS_ALL)
        self.assertEqual(update_section_state(current, "INDUSTRY OVERVIEW\nMarket size").policy, PROCESS_ISSUER_REVENUE_ONLY)
        self.assertEqual(
            update_section_state(current, "DIRECTORS AND SENIOR MANAGEMENT\nBiography").policy,
            PROCESS_DIRECTOR_EMOLUMENTS_ONLY,
        )
        self.assertEqual(update_section_state(current, "GLOBAL OFFERING\nStatistics").policy, SKIP_SECTION)

    def test_strong_non_comfort_page_is_skipped_even_inside_summary(self):
        page_text = """
        SUMMARY
        GLOBAL OFFERING STATISTICS
        Based on an Offer Price of HK$151.00 per Share
        """

        self.assertTrue(is_non_comfort_page(" ".join(page_text.lower().split())))
        self.assertTrue(should_skip_page(page_text, SectionState("summary", PROCESS_ALL)))

    def test_industry_overview_only_processes_issuer_revenue_lines(self):
        section = SectionState("industry overview", PROCESS_ISSUER_REVENUE_ONLY)

        self.assertTrue(should_process_line("Our revenue was US$300 million.", section))
        self.assertFalse(should_process_line("The market size was US$300 billion.", section))

    def test_director_section_only_processes_emoluments_lines(self):
        section = SectionState("directors/statutory", PROCESS_DIRECTOR_EMOLUMENTS_ONLY)

        self.assertTrue(should_process_line("Directors' emoluments were US$1.2 million.", section))
        self.assertFalse(should_process_line("Dr. Yan held 74,102,534 shares.", section))

    def test_financial_table_context_excludes_users_offering_and_proceeds(self):
        self.assertTrue(is_financial_table_context("Revenue – – 3,460 100.0 30,523 100.0"))
        self.assertTrue(is_financial_table_context("AI-native products 758 21.9 21,805 71.4 | Total revenue 3,460 100.0"))
        self.assertTrue(is_financial_table_context("Loss per share Basic and diluted (0.74) (2.56) (4.28)"))
        self.assertTrue(is_financial_table_context("Net cash used in operating activities (11,019) (64,455)"))
        self.assertTrue(is_financial_table_context("Five largest customers Revenue contribution HK$13.4 million 44.1%"))
        self.assertTrue(is_financial_table_context("Five largest suppliers Purchase amount US$49.8 million 63.0%"))
        self.assertTrue(is_financial_table_context("五大客户 收入贡献 13.4百万 44.1%"))
        self.assertTrue(is_financial_table_context("五大供应商 采购金额 49.8百万 63.0%"))
        self.assertFalse(is_financial_table_context("('000 users) AI-native products 11,131 115,378"))
        self.assertFalse(is_financial_table_context("Number of customers 11,131 115,378 212,247"))
        self.assertFalse(is_financial_table_context("Offer Price HK$151.00 per Share Global Offering"))
        self.assertFalse(is_financial_table_context("Use of Proceeds 90.0% HK$3,436.4 million"))
        self.assertFalse(is_financial_table_context("Pricing Strategy Monetization Method Currency Price Range USD 19.69 US$15"))

    def test_should_process_table_region_uses_section_and_context(self):
        financial_region = detect_table_numeric_regions(
            fitz,
            [
                [word(80, 100, "Revenue", 45), word(200, 100, "1,000"), word(260, 100, "2,000"), word(320, 100, "3,000")],
                [word(80, 115, "Cost", 25), word(200, 115, "(100)"), word(260, 115, "(200)"), word(320, 115, "(300)")],
                [word(80, 130, "Total", 28), word(200, 130, "900"), word(260, 130, "1,800"), word(320, 130, "2,700")],
            ],
        )[0]
        core = SectionState("financial information", PROCESS_ALL)
        skipped = SectionState("other", SKIP_SECTION)

        self.assertTrue(should_process_table_region("FINANCIAL INFORMATION", financial_region, core))
        self.assertFalse(should_process_table_region("GLOBAL OFFERING", financial_region, skipped))

    def test_table_context_uses_header_and_full_body(self):
        lines = [
            [word(360, 80, "US$"), word(430, 80, "%")],
            [word(80, 100, "AI-native"), word(120, 100, "products"), word(200, 100, "-"), word(260, 100, "758"), word(320, 100, "21.9")],
            [word(80, 115, "Services"), word(200, 115, "-"), word(260, 115, "2,702"), word(320, 115, "78.1")],
            [word(80, 130, "Total"), word(110, 130, "revenue"), word(200, 130, "-"), word(260, 130, "3,460"), word(320, 130, "100.0")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertIn("Total revenue", regions[0].context)
        self.assertTrue(is_financial_table_context(regions[0].context))

    def test_user_unit_header_excludes_user_table(self):
        lines = [
            [word(260, 80, "('000"), word(300, 80, "users)")],
            [word(80, 100, "AI-native"), word(120, 100, "products"), word(200, 100, "-"), word(260, 100, "11,131"), word(320, 100, "115,378")],
            [word(80, 115, "MiniMax"), word(200, 115, "-"), word(260, 115, "686"), word(320, 115, "13,541")],
            [word(80, 130, "Total"), word(200, 130, "-"), word(260, 130, "11,144"), word(320, 130, "115,420")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertIn("users", regions[0].context)
        self.assertFalse(is_financial_table_context(regions[0].context))

    def test_customer_supplier_financial_header_enables_table(self):
        lines = [
            [word(200, 80, "Revenue"), word(250, 80, "contribution"), word(330, 80, "%")],
            [word(80, 100, "Customer"), word(200, 100, "13,400"), word(260, 100, "44.1")],
            [word(80, 115, "Customer"), word(200, 115, "11,600"), word(260, 115, "21.7")],
            [word(80, 130, "Customer"), word(200, 130, "7,800"), word(260, 130, "14.7")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertTrue(is_financial_table_context(regions[0].context))

    def test_adjacent_financial_table_regions_are_merged(self):
        first = TableRegion(
            rect=fitz.Rect(200, 100, 520, 220),
            row_count=8,
            context="Revenue and cost of sales",
        )
        second = TableRegion(
            rect=fitz.Rect(210, 280, 515, 430),
            row_count=10,
            context="Assets and liabilities",
        )

        merged = merge_table_regions(fitz, [first, second])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].row_count, 18)
        self.assertLessEqual(merged[0].rect.y0, 100)
        self.assertGreaterEqual(merged[0].rect.y1, 430)


if __name__ == "__main__":
    unittest.main()
