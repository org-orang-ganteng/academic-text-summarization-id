#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Scrape Jurnal Indonesia → Dataset CSV

Script ini otomatis:
1. Crawl portal jurnal OJS Indonesia (open-access)
2. Download PDF artikel
3. Extract teks dari PDF
4. Pisahkan abstrak sebagai summary
5. Simpan ke data/raw/dataset.csv

CARA PAKAI:
    python scrape_journals.py

Target: 100 jurnal berbahasa Indonesia dari berbagai portal OJS.
"""

import os
import re
import sys
import time
import random
import tempfile
import traceback
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import pandas as pd

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF belum terinstall. Jalankan: pip install PyMuPDF")
    sys.exit(1)

# ============================================================
# Config
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(BASE_DIR, "data", "raw", "dataset.csv")
TEXT_COLUMN = "full_text"
SUMMARY_COLUMN = "summary"
TARGET_COUNT = 100  # target total jurnal di dataset

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

# Daftar issue URL dari berbagai jurnal OJS Indonesia (open-access, bahasa Indonesia)
JOURNAL_ISSUES = [
    # RETORIKA - Bahasa, Sastra, dan Pengajarannya (UNM)
    "https://ojs.unm.ac.id/retorika/issue/view/2836",
    "https://ojs.unm.ac.id/retorika/issue/view/2630",
    "https://ojs.unm.ac.id/retorika/issue/view/2459",
    "https://ojs.unm.ac.id/retorika/issue/view/2191",
    "https://ojs.unm.ac.id/retorika/issue/view/2187",
    "https://ojs.unm.ac.id/retorika/issue/view/1793",
    "https://ojs.unm.ac.id/retorika/issue/view/1436",
    "https://ojs.unm.ac.id/retorika/issue/view/1317",
    "https://ojs.unm.ac.id/retorika/issue/view/1101",
    "https://ojs.unm.ac.id/retorika/issue/view/974",
    # Jurnal Pendidikan Bahasa dan Sastra Daerah (UNM)
    "https://ojs.unm.ac.id/jurdisada/issue/view/2780",
    "https://ojs.unm.ac.id/jurdisada/issue/view/2443",
    # JEST - Journal of Educational Science and Technology (UNM)
    "https://ojs.unm.ac.id/JEST/issue/view/2834",
    "https://ojs.unm.ac.id/JEST/issue/view/2610",
    "https://ojs.unm.ac.id/JEST/issue/view/2338",
    # Daya Matematis (UNM)
    "https://ojs.unm.ac.id/JDM/issue/view/2811",
    "https://ojs.unm.ac.id/JDM/issue/view/2577",
    # Pinisi Journal of Education and Management
    "https://ojs.unm.ac.id/PJoEM/issue/view/2840",
    "https://ojs.unm.ac.id/PJoEM/issue/view/2622",
    # KREASI (UNM)
    "https://ojs.unm.ac.id/kreasi/issue/view/2845",
    "https://ojs.unm.ac.id/kreasi/issue/view/2637",
]

# ============================================================
# PDF Text Cleaning
# ============================================================
def clean_pdf_text(text: str) -> str:
    """Clean common PDF extraction artifacts."""
    lines = text.split('\n')
    line_counts = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 3:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1
    repeated_lines = {l for l, c in line_counts.items() if c >= 3}

    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped in repeated_lines:
            continue
        if re.match(r'^\s*\d{1,4}\s*$', line):
            continue
        if re.search(r'\(\d{4}\)\s*,?\s*\d+\s*\(\d+\)\s*:\s*\d+', stripped):
            continue
        if re.match(r'^\s*(https?://)?doi\.org\s*/\s*\S+', stripped, re.I):
            continue
        if re.match(r'^\s*(e-?issn|p-?issn|issn|doi)\s*[:/]\s*\S+', stripped, re.I):
            continue
        if re.match(r'^\s*https?://\S+\s*$', line):
            continue
        if re.match(r'^\s*\*?\s*\S+@\S+\.\S+\s*$', line):
            continue
        if re.match(r'^\s*volume\s+\d+\s*[–—-]\s*issue\s+\d+\s*[–—-]\s*\d{4}\s*$', stripped, re.I):
            continue
        cleaned.append(line)

    text = '\n'.join(cleaned)
    text = re.sub(r'(?si)\n\s*(DAFTAR\s+PUSTAKA|REFERENSI|REFERENCES|BIBLIOGRAPHY)\s*\n.*$', '', text)
    text = re.sub(r'(?<=[a-zA-Z])\d{1,2}(?=[\s,;])', '', text)
    text = re.sub(r'(?m)^\s*\d{1,2}(?=[A-Z])', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_abstract(text: str) -> tuple:
    """Pisahkan abstrak dari teks. Return: (abstract, full_text)"""
    abstract_match = re.search(
        r'(?i)\b(Abstrak|Abstract)\s*[:\n](.*?)(?=\n\s*(?:Kata\s+kunci|Keywords?|Abstract|PENDAHULUAN|INTRODUCTION|1\.\s)|$)',
        text, re.DOTALL
    )
    if abstract_match:
        abstract = re.sub(r'\s+', ' ', abstract_match.group(2).strip())
        intro_match = re.search(r'\n\s*(PENDAHULUAN|INTRODUCTION|1\.\s)', text)
        if intro_match:
            full_text = text[intro_match.start():].strip()
        else:
            full_text = text
        if len(abstract) > 50:
            return abstract, full_text

    # Fallback: 3 kalimat pertama
    sentences = re.split(r'(?<=[.!?])\s+', text)
    summary = ' '.join(sentences[:3]) if len(sentences) >= 3 else text[:500]
    return summary, text


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF file."""
    doc = fitz.open(pdf_path)
    parts = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            parts.append(text.strip())
    doc.close()
    return "\n\n".join(parts)


# ============================================================
# Web Scraping
# ============================================================
def get_soup(url: str, session: requests.Session) -> BeautifulSoup:
    """Fetch URL and return BeautifulSoup object."""
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_article_links(issue_url: str, session: requests.Session) -> list:
    """Get article view links from an OJS issue page."""
    try:
        soup = get_soup(issue_url, session)
    except Exception as e:
        print(f"    ERROR fetching issue page: {e}")
        return []

    links = []
    # OJS 2.x: links in tocTitle or article titles
    for a in soup.select("a[href*='/article/view/']"):
        href = a.get("href", "")
        # Skip PDF galley links (contain /pdf or end with galley id)
        if "/article/view/" in href and "/pdf" not in href.lower():
            full_url = urljoin(issue_url, href)
            # Only article view links (not galley links like /view/123/456)
            parts = full_url.rstrip("/").split("/")
            view_idx = [i for i, p in enumerate(parts) if p == "view"]
            if view_idx:
                after_view = parts[view_idx[-1]+1:]
                if len(after_view) == 1:  # /article/view/ID only
                    if full_url not in links:
                        links.append(full_url)

    return links


def get_pdf_url_from_article(article_url: str, session: requests.Session) -> str:
    """Get PDF download URL from an OJS article page."""
    try:
        soup = get_soup(article_url, session)
    except Exception as e:
        print(f"    ERROR fetching article page: {e}")
        return None

    # Look for PDF galley link on article page
    for a in soup.select("a[href*='/article/view/']"):
        href = a.get("href", "")
        text = a.get_text(strip=True).upper()
        if "PDF" in text and "/article/view/" in href:
            # Convert /article/view/ID/pdf to /article/download/ID/pdf
            download_url = href.replace("/article/view/", "/article/download/")
            return download_url

    # Fallback: try common download patterns
    # Extract article ID from URL
    match = re.search(r'/article/view/(\d+)', article_url)
    if match:
        art_id = match.group(1)
        base = article_url.split("/article/view/")[0]
        for suffix in ["pdf", "pdf_1", "pdf1"]:
            test_url = f"{base}/article/download/{art_id}/{suffix}"
            try:
                resp = session.head(test_url, headers=HEADERS, timeout=10, allow_redirects=True)
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct.lower():
                    return test_url
            except Exception:
                pass

    return None


def download_pdf(url: str, session: requests.Session) -> str:
    """Download PDF to temp file. Returns path or None."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=60, stream=True)
        resp.raise_for_status()

        # Check if it's actually a PDF
        content_type = resp.headers.get("content-type", "")
        first_bytes = resp.content[:5]
        if b"%PDF" not in first_bytes and "pdf" not in content_type.lower():
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(resp.content)
        tmp.close()
        return tmp.name
    except Exception as e:
        print(f"    ERROR downloading PDF: {e}")
        return None


def scrape_abstract_from_html(article_url: str, session: requests.Session) -> str:
    """Try to scrape abstract directly from article HTML page."""
    try:
        soup = get_soup(article_url, session)
        # OJS abstract section
        abstract_div = soup.select_one("div.item.abstract, div#articleAbstract, "
                                        "div.article-abstract, section.abstract")
        if abstract_div:
            text = abstract_div.get_text(strip=True)
            # Remove leading "Abstract" or "Abstrak" label
            text = re.sub(r'^(?:Abstract|Abstrak)\s*', '', text, flags=re.I)
            if len(text) > 50:
                return re.sub(r'\s+', ' ', text)
    except Exception:
        pass
    return None


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("AUTO SCRAPE JURNAL INDONESIA → DATASET CSV")
    print("=" * 60)

    # Load existing dataset
    if os.path.exists(DATASET_PATH):
        df = pd.read_csv(DATASET_PATH)
        existing_count = len(df)
        print(f"Dataset existing: {existing_count} rows")
    else:
        df = pd.DataFrame(columns=[TEXT_COLUMN, SUMMARY_COLUMN])
        existing_count = 0

    needed = TARGET_COUNT - existing_count
    if needed <= 0:
        print(f"Target {TARGET_COUNT} sudah tercapai! ({existing_count} rows)")
        return

    print(f"Butuh {needed} jurnal lagi untuk mencapai target {TARGET_COUNT}")
    print(f"Akan crawl dari {len(JOURNAL_ISSUES)} issue jurnal...")
    print()

    session = requests.Session()
    new_count = 0
    error_count = 0
    processed_titles = set()

    # Collect existing texts to avoid duplicates (first 100 chars)
    existing_fingerprints = set()
    if existing_count > 0:
        for txt in df[TEXT_COLUMN].dropna():
            fp = re.sub(r'\s+', '', str(txt)[:200])
            existing_fingerprints.add(fp)

    for issue_idx, issue_url in enumerate(JOURNAL_ISSUES):
        if new_count >= needed:
            break

        print(f"\n[Issue {issue_idx+1}/{len(JOURNAL_ISSUES)}] {issue_url}")

        # Get article links
        article_links = get_article_links(issue_url, session)
        print(f"  Ditemukan {len(article_links)} artikel")

        for art_idx, article_url in enumerate(article_links):
            if new_count >= needed:
                break

            print(f"\n  [{art_idx+1}/{len(article_links)}] {article_url}")
            time.sleep(random.uniform(1, 3))  # be polite

            # 1. Get PDF URL
            pdf_url = get_pdf_url_from_article(article_url, session)
            if not pdf_url:
                print("    SKIP: PDF tidak ditemukan")
                error_count += 1
                continue

            # 2. Download PDF
            print(f"    Downloading PDF...")
            pdf_path = download_pdf(pdf_url, session)
            if not pdf_path:
                print("    SKIP: Download gagal atau bukan PDF")
                error_count += 1
                continue

            try:
                # 3. Extract text
                raw_text = extract_pdf_text(pdf_path)
                if len(raw_text.strip()) < 500:
                    print(f"    SKIP: Teks terlalu pendek ({len(raw_text)} chars)")
                    error_count += 1
                    continue

                # 4. Check for Indonesian content
                indo_words = ['dan', 'yang', 'untuk', 'dengan', 'dalam', 'pada', 'ini',
                              'dari', 'adalah', 'bahwa', 'the', 'and', 'of']
                text_lower = raw_text.lower()
                indo_score = sum(1 for w in ['dan', 'yang', 'untuk', 'dengan', 'dalam', 'pada'] 
                                if f' {w} ' in text_lower)

                # 5. Clean text
                cleaned_text = clean_pdf_text(raw_text)

                # 6. Check duplicate
                fp = re.sub(r'\s+', '', cleaned_text[:200])
                if fp in existing_fingerprints:
                    print("    SKIP: Duplikat")
                    continue
                existing_fingerprints.add(fp)

                # 7. Extract abstract
                # Try from HTML first
                html_abstract = scrape_abstract_from_html(article_url, session)

                if html_abstract and len(html_abstract) > 80:
                    abstract = html_abstract
                    # Remove abstract section from full_text
                    intro_match = re.search(r'\n\s*(PENDAHULUAN|INTRODUCTION|1\.\s)', cleaned_text)
                    if intro_match:
                        full_text = cleaned_text[intro_match.start():].strip()
                    else:
                        full_text = cleaned_text
                else:
                    abstract, full_text = extract_abstract(cleaned_text)

                # 8. Validate
                if len(full_text) < 300:
                    print(f"    SKIP: Full text terlalu pendek ({len(full_text)} chars)")
                    error_count += 1
                    continue

                # 9. Save
                new_row = pd.DataFrame([{TEXT_COLUMN: full_text, SUMMARY_COLUMN: abstract}])
                df = pd.concat([df, new_row], ignore_index=True)
                new_count += 1

                print(f"    OK! [{existing_count + new_count}/{TARGET_COUNT}] "
                      f"text: {len(full_text)} chars, abstract: {len(abstract)} chars")

            except Exception as e:
                print(f"    ERROR: {e}")
                error_count += 1
            finally:
                # Cleanup temp PDF
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass

            # Small delay between articles
            time.sleep(random.uniform(0.5, 1.5))

        # Delay between issues
        time.sleep(random.uniform(2, 4))

    # Save final dataset
    if new_count > 0:
        df.to_csv(DATASET_PATH, index=False)

    # Summary
    print("\n" + "=" * 60)
    print("SELESAI!")
    print(f"  Baru ditambahkan : {new_count} jurnal")
    print(f"  Error/skip       : {error_count}")
    print(f"  Total dataset    : {len(df)} rows")
    print(f"  Target           : {TARGET_COUNT}")
    print(f"  File             : {DATASET_PATH}")

    if len(df) < TARGET_COUNT:
        print(f"\n  CATATAN: Masih kurang {TARGET_COUNT - len(df)} jurnal.")
        print(f"  Tambahkan URL issue baru ke JOURNAL_ISSUES lalu jalankan ulang.")


if __name__ == "__main__":
    main()
