from __future__ import annotations

from pathlib import Path
import tempfile

import streamlit as st

from comfort_marker.pdf_marker import mark_pdf


st.set_page_config(
    page_title="Comfort Marker",
    page_icon="CM",
    layout="centered",
)


def main() -> None:
    st.title("Comfort Marker")
    st.caption("Upload a text-based prospectus PDF and download the marked PDF plus CSV review log.")

    uploaded_file = st.file_uploader("Prospectus PDF", type=["pdf"])

    col1, col2 = st.columns(2)
    with col1:
        mode = st.selectbox("Detection mode", ("conservative", "broad"), index=0)
    with col2:
        stroke_width = st.slider("Box thickness", min_value=0.5, max_value=2.0, value=0.8, step=0.1)

    table_regions = st.checkbox("Use large boxes for financial table data areas", value=True)

    if not uploaded_file:
        return

    if st.button("Mark PDF", type="primary"):
        process_pdf(
            uploaded_file.getvalue(),
            uploaded_file.name,
            mode=mode,
            table_regions=table_regions,
            stroke_width=stroke_width,
        )


def process_pdf(
    pdf_bytes: bytes,
    original_name: str,
    *,
    mode: str,
    table_regions: bool,
    stroke_width: float,
) -> None:
    stem = Path(original_name).stem or "prospectus"

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_pdf = temp_dir / f"{stem}.pdf"
        output_pdf = temp_dir / f"{stem}.comfort-marked.pdf"
        output_csv = temp_dir / f"{stem}.findings.csv"
        input_pdf.write_bytes(pdf_bytes)

        with st.spinner("Marking PDF..."):
            findings = mark_pdf(
                input_pdf,
                output_pdf,
                csv_path=output_csv,
                mode=mode,
                table_regions=table_regions,
                stroke_width=stroke_width,
            )

        st.success(f"Marked {len(findings)} item(s).")

        pdf_output = output_pdf.read_bytes()
        csv_output = output_csv.read_bytes()

    st.download_button(
        "Download marked PDF",
        data=pdf_output,
        file_name=f"{stem}.comfort-marked.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    st.download_button(
        "Download CSV review log",
        data=csv_output,
        file_name=f"{stem}.findings.csv",
        mime="text/csv",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
