"""docs/REPORT.md -> docs/REPORT.html -> docs/REPORT.pdf (headless Microsoft Edge).

    .venv\\Scripts\\python.exe tools/build_pdf.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EDGE_CANDIDATES = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                   Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]

CSS = """
@page { size: A4; margin: 18mm 17mm; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10.2pt; line-height: 1.42; color: #111; }
h1 { font-size: 18pt; margin: 0 0 4pt 0; line-height: 1.2; }
h2 { font-size: 13pt; margin: 14pt 0 4pt 0; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 11pt; margin: 10pt 0 3pt 0; }
p, li { text-align: left; }
img[alt^="Same source"] { max-width: 58%; }
img[alt^="Replication"] { max-width: 70%; }
table { border-collapse: collapse; margin: 6pt 0; font-size: 8.8pt; width: 100%; }
th, td { border: 1px solid #bbb; padding: 3pt 5pt; vertical-align: top; }
th { background: #f1f3f5; }
img { max-width: 100%; display: block; margin: 6pt auto 2pt auto; }
blockquote { margin: 4pt 0 4pt 12pt; padding-left: 8pt; border-left: 3px solid #adb5bd; color: #333; }
code { font-family: Consolas, monospace; font-size: 8.8pt; background: #f4f4f4; padding: 0 2pt; }
pre { background: #f4f4f4; padding: 5pt; font-size: 8.3pt; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
em { color: #333; }
"""


def build(stem: str, edge: str, extra_css: str = "") -> Path:
    md = (DOCS / f"{stem}.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code"])
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
