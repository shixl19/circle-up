import unittest

import fitz

from comfort_marker.pdf_marker import (
    detect_table_numeric_regions,
    is_appendix_page,
    is_dash_word,
    is_non_comfort_table_region,
    is_placeholder_word,
    is_table_data_cell_word,
    should_skip_page,
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


if __name__ == "__main__":
    unittest.main()
