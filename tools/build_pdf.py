"""docs/REPORT.md -> docs/REPORT.html -> docs/REPORT.pdf (headless Microsoft Edge).

    .venv\\Scripts\\python.exe tools/build_pdf.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EDGE_CANDIDATES = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                   Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]

FONTS = "".join(
    f"@font-face {{ font-family: '{fam}'; font-style: {st}; font-weight: {w}; src: url('fonts/{f}.ttf'); }}\n"
    for fam, st, w, f in [("Crimson Pro", "normal", 400, "CrimsonPro-Regular"),
                          ("Crimson Pro", "italic", 400, "CrimsonPro-Italic"),
                          ("Crimson Pro", "normal", 600, "CrimsonPro-SemiBold"),
                          ("Crimson Pro", "italic", 600, "CrimsonPro-SemiBoldItalic"),
                          ("Old Standard TT", "normal", 400, "OldStandardTT-Regular"),
                          ("Old Standard TT", "italic", 400, "OldStandardTT-Italic"),
                          ("Old Standard TT", "normal", 700, "OldStandardTT-Bold")])

# Visual style of the official Apart Research submission template (Google Doc): serif body, Old Standard TT
# headings, title in capitals between a heavy and a thin rule, centred authors, "With Apart Research", centred
# italic abstract in a narrow column, title footnote naming the sprint.
CSS = FONTS + """
@page { size: A4; margin: 20mm 19mm; }
body { font-family: "Crimson Pro", Georgia, serif; font-size: 11.6pt; line-height: 1.3; color: #111; }
h1, h2, h3 { font-family: "Old Standard TT", Georgia, serif; font-weight: 700; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; line-height: 1.2; }
.titleblock { text-align: center; margin-bottom: 8pt; }
h1.title { text-transform: uppercase; font-size: 17pt; letter-spacing: 0.3pt; line-height: 1.3;
           border-top: 3.5pt solid #000; border-bottom: 0.8pt solid #000; padding: 14pt 4pt 14pt 4pt;
           margin: 0 0 12pt 0; }
h1.title sup { font-size: 9pt; }
.authors { display: flex; justify-content: center; gap: 40pt; font-family: "Old Standard TT", serif;
           font-size: 10.5pt; line-height: 1.35; }
.with { font-family: "Old Standard TT", serif; font-size: 10.5pt; margin-top: 8pt; line-height: 1.35; }
h2.abstract-h { text-align: center; border: none; font-size: 13pt; margin: 8pt 0 4pt 0; }
.abstract { margin: 0 11%; font-style: italic; text-align: justify; font-size: 11.2pt; line-height: 1.3; }
.abstract p { text-align: justify; margin: 0; }
.abstract strong { font-weight: 600; }
.fn { font-size: 9pt; border-top: 0.6pt solid #000; width: 100%; padding-top: 3pt; margin: 10pt 0 2pt 0;
      line-height: 1.25; }
.fn a { color: #1a55c4; }
h2 { font-size: 14pt; margin: 14pt 0 4pt 0; }
h3 { font-size: 12pt; margin: 10pt 0 3pt 0; }
p { margin: 0 0 6pt 0; }
p, li { text-align: left; }
a { color: #1a55c4; }
img[alt^="Same evidence"] { max-width: 62%; }
img[alt^="True vs falsified"] { max-width: 72%; }
img[alt^="Follow rates"] { max-width: 88%; }
img[alt^="Replication"], img[alt^="Ember"] { max-width: 50%; }
figure { margin: 0; break-inside: avoid; page-break-inside: avoid; }
figure p { margin: 0 0 4pt 0; }
table, blockquote, pre, tr { break-inside: avoid; page-break-inside: avoid; }
h2, h3 { break-after: avoid; page-break-after: avoid; }
table { border-collapse: collapse; margin: 6pt 0; font-size: 10pt; width: 100%; line-height: 1.2; }
th, td { border: 1px solid #bbb; padding: 2.5pt 5pt; vertical-align: top; }
th { background: #f1f3f5; font-weight: 600; }
img { max-width: 100%; display: block; margin: 6pt auto 2pt auto; }
blockquote { margin: 4pt 0 4pt 12pt; padding-left: 8pt; border-left: 3px solid #adb5bd; color: #333; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f4f4f4; padding: 0 2pt; }
pre { background: #f4f4f4; padding: 5pt; font-size: 8.3pt; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
em { color: #222; }
strong { font-weight: 600; }
"""


def build(stem: str, edge: str, extra_css: str = "") -> Path:
    md = (DOCS / f"{stem}.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "md_in_html"])
    # keep each figure with its caption on one page
    body = re.sub(r"(<p><img [^>]+></p>\s*<p><em>Figure .*?</em></p>)", r"<figure>\1</figure>", body, flags=re.S)
    html = (f"<!doctype html><html><head><meta charset='utf-8'><title>Status or Evidence?</title>"
            f"<style>{CSS}{extra_css}</style></head><body>{body}</body></html>")
    html_path = DOCS / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = DOCS / f"{stem}.pdf"
    subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.as_uri()], check=True, timeout=120,
                   capture_output=True)
    print(f"-> {pdf_path.relative_to(ROOT)} ({pdf_path.stat().st_size // 1024} KB)")
    return pdf_path


def main() -> int:
    edge = next((str(p) for p in EDGE_CANDIDATES if p.exists()), None) or shutil.which("msedge")
    if not edge:
        print("Microsoft Edge not found; open docs/REPORT.html and print to PDF")
        return 1
    build("REPORT", edge)
    build("JUDGE", edge, "h1{font-size:16pt} p,li{font-size:10pt} img{max-height:300px;width:auto;margin-left:0}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
