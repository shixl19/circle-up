from __future__ import annotations

import argparse
from pathlib import Path

from .pdf_marker import mark_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Draw red boxes around prospectus figures likely requiring accountant comfort."
    )
    parser.add_argument("input_pdf", type=Path, help="Source prospectus PDF")
    parser.add_argument("-o", "--output", type=Path, help="Marked output PDF")
    parser.add_argument("--csv", type=Path, help="CSV review log path")
    parser.add_argument(
        "--mode",
        choices=("conservative", "broad"),
        default="conservative",
        help="Detection mode. Conservative is default; broad captures more numbers.",
    )
    parser.add_argument(
        "--stroke-width",
        type=float,
        default=0.8,
        help="Red box stroke width in PDF points.",
    )
    parser.add_argument(
        "--no-table-regions",
        action="store_true",
        help="Disable large boxes around financial table numeric areas.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_pdf = args.input_pdf
    output_pdf = args.output or input_pdf.with_name(f"{input_pdf.stem}.comfort-marked.pdf")
    csv_path = args.csv or output_pdf.with_suffix(".csv")

    findings = mark_pdf(
        input_pdf,
        output_pdf,
        csv_path=csv_path,
        mode=args.mode,
        table_regions=not args.no_table_regions,
        stroke_width=args.stroke_width,
    )

    print(f"Marked {len(findings)} figure(s).")
    print(f"PDF: {output_pdf}")
    print(f"CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
