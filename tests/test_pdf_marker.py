import unittest

import fitz

from comfort_marker.pdf_marker import (
    SectionState,
    PROCESS_ALL,
    PROCESS_DIRECTOR_EMOLUMENTS_ONLY,
    PROCESS_ISSUER_REVENUE_ONLY,
    SKIP_SECTION,
    detect_table_numeric_regions,
    is_appendix_page,
    is_financial_table_context,
    is_dash_word,
    is_non_comfort_table_region,
    is_placeholder_word,
    is_table_data_cell_word,
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
        self.assertFalse(is_financial_table_context("('000 users) AI-native products 11,131 115,378"))
        self.assertFalse(is_financial_table_context("Offer Price HK$151.00 per Share Global Offering"))
        self.assertFalse(is_financial_table_context("Use of Proceeds 90.0% HK$3,436.4 million"))

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


if __name__ == "__main__":
    unittest.main()
