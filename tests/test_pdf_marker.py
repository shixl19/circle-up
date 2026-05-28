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
        self.assertTrue(is_appendix_page("Page 594\nAPPENDIX I ACCOUNTANT'S REPORT\nNotes to Historical Financial Information"))
        self.assertTrue(
            is_appendix_page("Notes to Historical Financial Information\nRevenue 1,000 2,000\nAPPENDIX I ACCOUNTANT’S REPORT")
        )
        self.assertFalse(is_appendix_page("The financial statements included in Appendix I to this Prospectus."))
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
        self.assertEqual(
            update_section_state(
                current,
                "This summary aims to give you an overview of the information contained in this\n"
                "Prospectus. As it is a summary, it does not contain all the information.",
            ).policy,
            PROCESS_ALL,
        )
        self.assertEqual(
            update_section_state(
                SectionState("summary", PROCESS_ALL),
                "The table below sets out the beneficial interests entitled to and voting rights to be held\n"
                "by the WVR Beneficiaries upon completion of the Global Offering\n"
                "number of\nclass b\nordinary shares\nheld\nnumber of class\na ordinary\n"
                "shares interested\nin\napproximate\npercentage\nbeneficial\ninterests\n"
                "share capital\napproximate percentage",
            ).policy,
            PROCESS_ALL,
        )
        self.assertEqual(update_section_state(current, "INDUSTRY OVERVIEW\nMarket size").policy, SKIP_SECTION)
        self.assertEqual(
            update_section_state(current, "DIRECTORS AND SENIOR MANAGEMENT\nBiography").policy,
            PROCESS_DIRECTOR_EMOLUMENTS_ONLY,
        )
        self.assertEqual(update_section_state(current, "GLOBAL OFFERING\nStatistics").policy, SKIP_SECTION)
        self.assertEqual(update_section_state(current, "CORNERSTONE INVESTORS\nThe Cornerstone Placing").policy, SKIP_SECTION)
        self.assertEqual(update_section_state(current, "Overview\nBUSINESS\n- 236 -").policy, PROCESS_ALL)
        self.assertEqual(update_section_state(current, "APPENDIX III\nSUMMARY OF THE CONSTITUTION").policy, SKIP_SECTION)
        self.assertEqual(
            update_section_state(current, "DIRECTORS AND SENIOR MANAGEMENT . . . . . . . . . . . . . . 350").policy,
            SKIP_SECTION,
        )

    def test_strong_non_comfort_page_is_skipped_even_inside_summary(self):
        page_text = """
        SUMMARY
        GLOBAL OFFERING STATISTICS
        Based on an Offer Price of HK$151.00 per Share
        """

        self.assertTrue(is_non_comfort_page(" ".join(page_text.lower().split())))
        self.assertTrue(should_skip_page(page_text, SectionState("summary", PROCESS_ALL)))

    def test_offering_pro_forma_and_proceeds_pages_are_skipped(self):
        samples = [
            "UNAUDITED PRO FORMA STATEMENT OF ADJUSTED CONSOLIDATED NET TANGIBLE ASSETS\nBased on an Offer Price of HK$151.00 per Share",
            "We plan to allocate approximately 20.0%, or HK$763.7 million, of the net proceeds over the next five years.",
        ]

        for page_text in samples:
            with self.subTest(page_text=page_text):
                self.assertTrue(should_skip_page(page_text, SectionState("financial information", PROCESS_ALL)))

    def test_history_and_regulatory_pages_are_skipped(self):
        samples = [
            "HISTORY, REORGANIZATION AND CORPORATE STRUCTURE\nWe spent R&D expenses of US$80 thousand.",
            "REGULATORY OVERVIEW\nPenalties may be up to $53,000 per violation.",
        ]

        for page_text in samples:
            with self.subTest(page_text=page_text):
                self.assertTrue(should_skip_page(page_text, SectionState("business", PROCESS_ALL)))

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
        self.assertTrue(is_financial_table_context("aging analysis of our trade receivables (US$ in thousands) Within one year 1,338 6,982"))
        self.assertTrue(is_financial_table_context("trade receivables turnover days (days) N/A 41 49 38"))
        self.assertFalse(is_financial_table_context("('000 users) AI-native products 11,131 115,378"))
        self.assertFalse(is_financial_table_context("Number of customers 11,131 115,378 212,247"))
        self.assertFalse(is_financial_table_context("Indicators/Unit Energy consumption (kwh) 20,983.24 214,691.12"))
        self.assertFalse(is_financial_table_context("Municipal water consumption per unit of revenue 68.37 577.08"))
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

    def test_product_revenue_breakdown_table_without_early_revenue_label_is_financial(self):
        lines = [
            [word(230, 60, "US$"), word(280, 60, "%"), word(330, 60, "US$"), word(380, 60, "%")],
            [word(180, 80, "(in"), word(205, 80, "thousands,"), word(265, 80, "except"), word(310, 80, "for"), word(335, 80, "percentages)")],
            [word(80, 100, "AI-native"), word(120, 100, "products")],
            [word(80, 115, "MiniMax"), word(200, 115, "-"), word(250, 115, "-"), word(300, 115, "756"), word(350, 115, "1.4")],
            [word(80, 130, "Hailuo"), word(120, 130, "AI"), word(200, 130, "-"), word(250, 130, "2,347"), word(300, 130, "17,464"), word(350, 130, "32.6")],
            [word(80, 145, "Talkie/Xingye"), word(200, 145, "758"), word(250, 145, "21.9"), word(300, 145, "18,750"), word(350, 145, "35.1")],
            [word(80, 160, "Total"), word(112, 160, "revenue"), word(200, 160, "-"), word(250, 160, "3,460"), word(300, 160, "53,437"), word(350, 160, "100.0")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
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

    def test_financial_prose_is_not_treated_as_table(self):
        lines = [
            [
                word(80, 100, "Our", 15),
                word(100, 100, "net", 16),
                word(120, 100, "liabilities", 45),
                word(170, 100, "increased", 42),
                word(218, 100, "from", 20),
                word(244, 100, "US$343.3", 40),
                word(290, 100, "million", 30),
                word(326, 100, "to", 10),
                word(342, 100, "US$902.0", 40),
                word(388, 100, "million", 30),
                word(424, 100, "in", 8),
                word(438, 100, "2024.", 25),
            ],
            [
                word(80, 116, "primarily", 38),
                word(122, 116, "due", 16),
                word(143, 116, "to", 10),
                word(158, 116, "an", 10),
                word(173, 116, "increase", 36),
                word(214, 116, "from", 20),
                word(240, 116, "US$629.0", 40),
                word(286, 116, "million", 30),
                word(322, 116, "to", 10),
                word(338, 116, "US$1,581.9", 48),
                word(392, 116, "million", 30),
                word(428, 116, "and", 16),
            ],
            [
                word(80, 132, "trade", 25),
                word(110, 132, "payables", 36),
                word(151, 132, "from", 20),
                word(177, 132, "US$17.2", 35),
                word(218, 132, "million", 30),
                word(254, 132, "to", 10),
                word(270, 132, "US$51.2", 35),
                word(311, 132, "million", 30),
                word(347, 132, "as", 10),
                word(363, 132, "of", 10),
                word(379, 132, "December", 38),
                word(423, 132, "31,", 14),
                word(443, 132, "2024.", 25),
            ],
        ]

        self.assertEqual(detect_table_numeric_regions(fitz, lines), [])

    def test_key_financial_ratios_table_with_na_is_detected(self):
        lines = [
            [word(80, 70, "KEY"), word(110, 70, "FINANCIAL"), word(170, 70, "RATIOS")],
            [word(250, 90, "2022"), word(310, 90, "2023"), word(370, 90, "2024"), word(430, 90, "2025")],
            [word(80, 110, "Revenue"), word(125, 110, "growth"), word(250, 110, "N/A"), word(310, 110, "N/A"), word(370, 110, "782.2%"), word(430, 110, "174.7%")],
            [word(80, 125, "Gross"), word(115, 125, "margin"), word(250, 125, "N/A"), word(310, 125, "(24.7%)"), word(370, 125, "12.2%"), word(430, 125, "23.3%")],
            [word(80, 140, "Current"), word(125, 140, "ratio"), word(250, 140, "0.49"), word(310, 140, "0.48"), word(370, 140, "0.47"), word(430, 140, "0.43")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertTrue(is_financial_table_context(regions[0].context))
        self.assertTrue(
            should_process_table_region(
                "KEY FINANCIAL RATIOS\nAPPLICATION FOR LISTING ON THE STOCK EXCHANGE",
                regions[0],
                SectionState("business", PROCESS_ALL),
            )
        )
        self.assertFalse(
            should_skip_page(
                "KEY FINANCIAL RATIOS\nRevenue growth N/A N/A 782.2% 174.7%\n"
                "Offer Price and Offer Size Adjustment Option are discussed below.",
                SectionState("business", PROCESS_ALL),
            )
        )

    def test_financial_table_does_not_merge_following_prose(self):
        lines = [
            [word(80, 70, "As"), word(105, 70, "of"), word(200, 70, "2022"), word(260, 70, "2023"), word(320, 70, "2024"), word(380, 70, "2025")],
            [word(80, 90, "CURRENT"), word(140, 90, "LIABILITIES")],
            [word(80, 110, "Trade"), word(120, 110, "payables"), word(200, 110, "2,394"), word(260, 110, "17,242"), word(320, 110, "51,212"), word(380, 110, "70,219")],
            [word(80, 125, "Lease"), word(120, 125, "liabilities"), word(200, 125, "349"), word(260, 125, "1,248"), word(320, 125, "1,964"), word(380, 125, "1,694")],
            [word(80, 140, "Total"), word(120, 140, "current"), word(175, 140, "liabilities"), word(200, 140, "150,244"), word(260, 140, "662,791"), word(320, 140, "1,707,645"), word(380, 140, "2,434,187")],
            [
                word(80, 165, "Our", 15),
                word(100, 165, "net", 16),
                word(122, 165, "current", 34),
                word(162, 165, "liabilities", 45),
                word(212, 165, "increased", 42),
                word(260, 165, "from", 20),
                word(286, 165, "US$77.0", 35),
                word(327, 165, "million", 30),
                word(363, 165, "to", 10),
                word(379, 165, "US$343.3", 40),
                word(425, 165, "million", 30),
            ],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertLess(regions[0].rect.y1, 155)

    def test_financial_table_extends_to_sparse_loss_per_share_row(self):
        lines = [
            [word(80, 70, "Revenue"), word(200, 70, "1,000"), word(260, 70, "100.0"), word(320, 70, "2,000"), word(380, 70, "100.0")],
            [word(80, 85, "Cost"), word(200, 85, "(800)"), word(260, 85, "(80.0)"), word(320, 85, "(1,600)"), word(380, 85, "(80.0)")],
            [word(80, 100, "Loss"), word(200, 100, "(100)"), word(260, 100, "(10.0)"), word(320, 100, "(200)"), word(380, 100, "(10.0)")],
            [word(80, 126, "Loss"), word(112, 126, "per"), word(138, 126, "share")],
            [word(80, 140, "Basic"), word(120, 140, "and"), word(150, 140, "diluted")],
            [word(80, 154, "year/period"), word(200, 154, "(0.74)"), word(320, 154, "(2.56)")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].row_count, 4)
        self.assertGreater(regions[0].rect.y1, 160)

    def test_single_row_aging_and_turnover_tables_are_detected(self):
        aging_lines = [
            [word(80, 70, "aging"), word(118, 70, "analysis"), word(165, 70, "of"), word(182, 70, "trade"), word(215, 70, "receivables")],
            [word(240, 95, "2022"), word(300, 95, "2023"), word(360, 95, "2024"), word(420, 95, "2025")],
            [word(230, 115, "(US$"), word(265, 115, "in"), word(282, 115, "thousands)")],
            [word(80, 140, "Within"), word(125, 140, "one"), word(155, 140, "year"), word(240, 140, "-"), word(300, 140, "1,338"), word(360, 140, "6,982"), word(420, 140, "8,063")],
        ]
        turnover_lines = [
            [word(80, 70, "trade"), word(115, 70, "receivables"), word(180, 70, "turnover"), word(238, 70, "days")],
            [word(230, 95, "(days)")],
            [word(80, 120, "days(1)"), word(240, 120, "N/A"), word(300, 120, "41"), word(360, 120, "49"), word(420, 120, "38")],
        ]

        self.assertEqual(len(detect_table_numeric_regions(fitz, aging_lines)), 1)
        self.assertEqual(len(detect_table_numeric_regions(fitz, turnover_lines)), 1)

    def test_environmental_metrics_table_is_not_financial(self):
        lines = [
            [word(80, 70, "Indicators/Unit"), word(240, 70, "2022"), word(300, 70, "2023"), word(360, 70, "2024"), word(420, 70, "2025")],
            [word(80, 95, "Energy"), word(130, 95, "consumption"), word(240, 95, "20,983.24"), word(300, 95, "214,691.12"), word(360, 95, "566,043.73"), word(420, 95, "735,824.16")],
            [word(80, 110, "Municipal"), word(140, 110, "water"), word(240, 110, "0"), word(300, 110, "68.37"), word(360, 110, "577.08"), word(420, 110, "935.64")],
            [word(80, 125, "Wastewater"), word(145, 125, "discharge"), word(240, 125, "0"), word(300, 125, "54.70"), word(360, 125, "461.66"), word(420, 125, "748.51")],
        ]

        regions = detect_table_numeric_regions(fitz, lines)

        self.assertEqual(len(regions), 1)
        self.assertFalse(is_financial_table_context(regions[0].context))

    def test_discussion_of_financial_position_does_not_switch_to_appendix(self):
        current = SectionState("business", PROCESS_ALL)
        page_text = (
            "DISCUSSION OF CERTAIN KEY ITEMS FROM OUR CONSOLIDATED STATEMENTS OF FINANCIAL POSITION\n"
            "The table below sets forth selected information from our consolidated financial statements "
            "included in Appendix I to this Prospectus."
        )

        self.assertEqual(update_section_state(current, page_text).policy, PROCESS_ALL)

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
