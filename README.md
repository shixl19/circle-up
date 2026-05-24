# Circleup Comfort Marker

Circleup Comfort Marker marks prospectus figures that may need accountant comfort.

It reads a text-based PDF, draws red boxes around likely comfort items, and writes a CSV review log. It is designed for Hong Kong IPO prospectus drafting workflows where lawyers need to identify financial figures for accountant review.

## What It Marks

- Issuer financial figures in Summary, Risk Factors, Business, and Financial Information
- Issuer revenue figures in Industry Overview, when the line refers to the prospectus company's revenue
- Financial table data areas, including numbers, dashes used as nil/zero values, and draft placeholders such as `[768]`, `[*]`, and `[·]`
- Directors' emoluments / remuneration, including where this appears in Statutory and General Information

## What It Skips

- Market or industry data, such as market size, market share, GDP, CAGR, IDC / Frost & Sullivan statistics
- Offering, share capital, shareholding, voting rights, Offer Shares, Offer Price, and Global Offering figures
- Use of proceeds / net proceeds / IPO proceeds allocation figures
- User, member, employee, customer, headcount, and similar non-financial operating tables or figures
- Sections outside the scoped chapters, unless directors' emoluments / remuneration is mentioned
- Appendix pages by default, except directors' emoluments / remuneration

## Requirements

- Python 3.10 or later
- Text-based PDFs, not scanned image PDFs

## Install On macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
```

## Install On Windows

Open PowerShell in the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .
```

If PowerShell blocks activation, run this once for the current PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Run

macOS:

```bash
comfort-marker input.pdf -o marked.pdf --csv findings.csv
```

Windows PowerShell:

```powershell
comfort-marker .\input.pdf -o .\marked.pdf --csv .\findings.csv
```

You can also run without the installed shortcut:

```bash
python -m comfort_marker.cli input.pdf -o marked.pdf --csv findings.csv
```

## Detection Modes

The default mode is conservative:

```bash
comfort-marker input.pdf -o marked.pdf --csv findings.csv
```

Use broad mode for a first-pass review that captures more numeric values:

```bash
comfort-marker input.pdf --mode broad -o broad-marked.pdf --csv broad-findings.csv
```

Disable large table-area boxes if you only want individual body-text matches:

```bash
comfort-marker input.pdf --no-table-regions -o marked.pdf --csv findings.csv
```

## Run The Web App Locally

Install the web dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the app:

```bash
streamlit run app.py
```

Then open the local URL shown in the terminal, upload a PDF, and download the marked PDF and CSV.

## Deploy A Web App From GitHub

The easiest hosted option is Streamlit Community Cloud:

1. Push this repository to GitHub.
2. Go to <https://share.streamlit.io/>.
3. Sign in with GitHub.
4. Select the repository.
5. Set the main file path to `app.py`.
6. Deploy.

After deployment, your team can use the generated web URL from macOS or Windows without installing Python locally.

Important: use a private repository and a private deployment option if prospectus drafts are confidential. Do not upload client documents to a public demo deployment.

## Test

```bash
python -m unittest discover -s tests
```

## GitHub Setup

Recommended repository settings:

- Use a private GitHub repository if prospectus drafts or client names may appear in branches, issues, or examples.
- Do not commit prospectus PDFs or generated CSV/PDF outputs. `.gitignore` excludes `*.pdf` and `*.csv` by default.
- Ask users to install Python 3.10+ from <https://www.python.org/downloads/> on Windows and tick "Add python.exe to PATH" during installation.
- For the web app, Streamlit reads dependencies from `requirements.txt` and runs `app.py`.

Initial upload:

```bash
git init
git add .
git commit -m "Initial comfort marker prototype"
git branch -M main
git remote add origin https://github.com/YOUR-ORG/circleup-comfort-marker.git
git push -u origin main
```

## Limitations

- Scanned PDFs need OCR before running this tool.
- The marking rules are judgment-based and should be calibrated against your firm's comfort practice.
- The output should be lawyer-reviewed before sending to accountants.
