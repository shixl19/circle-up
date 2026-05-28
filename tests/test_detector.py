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

    def test_does_not_treat_year_plus_word_as_amount_suffix(self):
        text = "The balance was US$30.0 million as of November 30, 2025 mainly due to cash movements."

        self.assertEqual([hit.text for hit in find_numeric_hits(text)], ["US$30.0 million"])

    def test_broad_mode_captures_operating_numbers(self):
        hits = find_numeric_hits("The platform processed 12,500 workloads in 2025.", mode="broad")

        self.assertEqual([hit.text for hit in hits], ["12,500"])

    def test_marks_trillion_amounts(self):
        hits = find_numeric_hits("AI will contribute US$19.9 trillion to the global economy.")

        self.assertEqual([hit.text for hit in hits], ["US$19.9 trillion"])

    def test_skips_market_size_data(self):
        text = "The global foundation model market size is projected to exceed US$300 billion by 2030."

        self.assertEqual(find_numeric_hits(text), [])

    def test_skips_market_cagr_even_when_revenue_is_nearby(self):
        text = (
            "The global model-based foundation model market is expected to grow rapidly from "
            "US$10.7 billion in 2024 to US$206.5 billion by 2029, representing a CAGR of 80.7%."
        )

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

    def test_skips_non_financial_operating_headcount(self):
        text = "We have built an R&D team of around 300 members, structured into specialized groups."

        self.assertEqual(find_numeric_hits(text), [])

    def test_skips_non_financial_employee_percentages(self):
        samples = [
            "R&D personnel accounted for 71.0% of non-manufacturing employees.",
            "Active users represented 56.3% of all registered users.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(find_numeric_hits(sample), [])

    def test_skips_environmental_metrics(self):
        samples = [
            "Energy consumption per unit of revenue was 13,760.67 kwh/US$ ten thousand.",
            "Municipal water consumption was 935.64 ton and wastewater discharge was 748.51 ton.",
            "Greenhouse gas emissions per unit of revenue was 7.96 ton of carbon dioxide equivalent.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(find_numeric_hits(sample), [])

    def test_skips_shareholding_and_voting_rights_data(self):
        samples = [
            "Dr. Yan is interested in 67.1% and 32.9% of the voting rights.",
            "The approximate percentage of beneficial interests in the issued share capital was 25.36%.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(find_numeric_hits(sample), [])

    def test_marks_financial_turnover_days(self):
        samples = [
            "Inventory turnover days were 89.4 days, 78.5 days and 61.1 days.",
            "Trade receivables turnover days were 82.4 days, 72.0 days and 69.5 days.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(
                    [hit.text for hit in find_numeric_hits(sample)],
                    [part.strip() for part in sample.split("were", 1)[1].replace("and", ",").strip(".").split(",")],
                )

    def test_skips_non_financial_day_counts(self):
        self.assertEqual(find_numeric_hits("The implementation timetable is expected to take 30 days."), [])


if __name__ == "__main__":
    unittest.main()
