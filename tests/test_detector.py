import unittest

from comfort_marker.detector import find_numeric_hits


class DetectorTests(unittest.TestCase):
    def test_marks_currency_and_percentages_in_financial_context(self):
        text = "Revenue increased by 35.2% from HK$1,234.5 million to HK$1,668.9 million."

        hits = find_numeric_hits(text)

        self.assertEqual(
            [hit.text for hit in hits],
            ["35.2%", "HK$1,234.5 million", "HK$1,668.9 million"],
        )

    def test_skips_plain_year_without_context(self):
        self.assertEqual(find_numeric_hits("The company was founded in 2018."), [])

    def test_skips_date_components_but_marks_amount(self):
        hits = find_numeric_hits("For the year ended December 31, 2025, gross profit was RMB88.0 million.")

        self.assertEqual([hit.text for hit in hits], ["RMB88.0 million"])

    def test_broad_mode_captures_operating_numbers(self):
        hits = find_numeric_hits("The platform had 12,500 active users in 2025.", mode="broad")

        self.assertEqual([hit.text for hit in hits], ["12,500"])

    def test_marks_trillion_amounts(self):
        hits = find_numeric_hits("AI will contribute US$19.9 trillion to the global economy.")

        self.assertEqual([hit.text for hit in hits], ["US$19.9 trillion"])

    def test_skips_market_size_data(self):
        text = "The global foundation model market size is projected to exceed US$300 billion by 2030."

        self.assertEqual(find_numeric_hits(text), [])

    def test_skips_market_share_data(self):
        text = "According to IDC, our market share was 3.5% in 2025."

        self.assertEqual(find_numeric_hits(text), [])

    def test_still_marks_issuer_financial_data(self):
        text = "Our revenue increased by 35.2% to US$300 million during the Track Record Period."

        self.assertEqual([hit.text for hit in find_numeric_hits(text)], ["35.2%", "US$300 million"])

    def test_skips_offering_and_share_capital_data(self):
        samples = [
            "The Offer Price is expected to be HK$151.0 per Share.",
            "The issued share capital will be 25,389,220 Shares immediately after the Global Offering.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(find_numeric_hits(sample), [])

    def test_skips_use_of_proceeds_data(self):
        samples = [
            "We expect to use 35.0% of the net proceeds, or HK$200.0 million, for R&D.",
            "With the estimated net IPO proceeds of US$468.7 million, our cash runway will extend.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(find_numeric_hits(sample), [])

    def test_marks_director_emoluments_exception(self):
        text = "Directors' emoluments amounted to US$1.2 million for the year ended December 31, 2025."

        self.assertEqual([hit.text for hit in find_numeric_hits(text)], ["US$1.2 million"])


if __name__ == "__main__":
    unittest.main()
