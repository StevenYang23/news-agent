"""Web scrapers for sources that publish text but have no clean RSS.

Currently implements Macro Voices (guest transcripts published as PDFs).
Each site's scraper returns normalized items (guid/title/url/published_at) and a
content resolver (PDF download + text extraction).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

MACROVOICES_LIST = "https://www.macrovoices.com/guest-content/list-guest-transcripts"


def fetch_macrovoices(limit: int = 5) -> list[dict]:
    """Scrape the Macro Voices guest-transcript list (title + date + PDF link)."""
    resp = requests.get(MACROVOICES_LIST, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=lambda h: h and "/file" in h)
        if not a:
            continue
        tds = tr.find_all("td")
        date_str = tds[2].get_text(strip=True) if len(tds) > 2 else ""

        title = re.sub(r"^pdf\s*", "", a.get_text(" ", strip=True), flags=re.I)
        title = re.sub(r"\(pdf.*?\)", "", title, flags=re.I).strip()

        try:
            dt = datetime.strptime(date_str, "%d %b %Y").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)

        url = "https://www.macrovoices.com" + a["href"]
        items.append(
            {
                "guid": a["href"],
                "title": title,
                "url": url,
                "published_at": dt.isoformat(),
                "pdf_url": url,
            }
        )
        if len(items) >= limit:
            break
    return items


def extract_pdf_text(pdf_url: str) -> str:
    """Download a PDF and extract its plain text."""
    import pymupdf  # noqa: PLC0415

    resp = requests.get(pdf_url, headers=_HEADERS, timeout=90)
    resp.raise_for_status()
    doc = pymupdf.open(stream=resp.content, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
