#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch PDF to CSV - Konversi semua PDF jurnal ke dataset.csv

CARA PAKAI:
1. Taruh semua file PDF jurnal ke folder: data/pdfs/
2. Jalankan: python batch_pdf_to_csv.py
3. Selesai! Semua jurnal otomatis masuk ke data/raw/dataset.csv

Catatan:
- Abstrak otomatis diambil sebagai 'summary'
- Teks full (tanpa abstrak & referensi) sebagai 'full_text'
- PDF yang sudah pernah diproses akan di-skip (tidak duplikat)
- Filter otomatis: header/footer berulang, nomor halaman, DOI, ISSN, email, URL
"""

import os
import re
import sys
import glob
import pandas as pd

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF belum terinstall. Jalankan: pip install PyMuPDF")
    sys.exit(1)

# ============================================================
# Config
# ============================================================
PDF_FOLDER = os.path.join(os.path.dirname(__file__), "data", "pdfs")
DATASET_PATH = os.path.join(os.path.dirname(__file__), "data", "raw", "dataset.csv")
TEXT_COLUMN = "full_text"
SUMMARY_COLUMN = "summary"


# ============================================================
# PDF Text Cleaning (sama dengan di app.py)
# ============================================================
def clean_pdf_text(text: str) -> str:
    """Clean common PDF extraction artifacts from text."""
    lines = text.split('\n')

    # Detect repeated header/footer lines (appear 3+ times)
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
    """
    Pisahkan abstrak dari teks.
    Return: (abstract, full_text_tanpa_abstract)
    """
    # Cari pola Abstrak/Abstract
    abstract_match = re.search(
        r'(?i)\b(Abstrak|Abstract)\s*\n(.*?)(?=\n\s*(?:Kata\s+kunci|Keywords?|Abstract|PENDAHULUAN|INTRODUCTION|1\.\s)|$)',
        text,
        re.DOTALL
    )

    if abstract_match:
        abstract = abstract_match.group(2).strip()
        # Bersihkan whitespace berlebih
        abstract = re.sub(r'\s+', ' ', abstract)

        # Cari semua abstrak (ID + EN) dan hapus dari full_text
        # Hapus dari awal sampai PENDAHULUAN/INTRODUCTION
        intro_match = re.search(r'\n\s*(PENDAHULUAN|INTRODUCTION|1\.\s)', text)
        if intro_match:
            full_text = text[intro_match.start():].strip()
        else:
            full_text = text
        return abstract, full_text

    # Fallback: tidak ketemu abstrak, pakai 2 kalimat pertama sebagai summary
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
# Main
# ============================================================
def main():
    # Cek folder PDF
    if not os.path.exists(PDF_FOLDER):
        os.makedirs(PDF_FOLDER)
        print(f"Folder dibuat: {PDF_FOLDER}")
        print("Taruh file PDF jurnal ke folder tersebut, lalu jalankan ulang script ini.")
        return

    # Cari semua PDF
    pdf_files = sorted(glob.glob(os.path.join(PDF_FOLDER, "*.pdf")))
    if not pdf_files:
        print(f"Tidak ada file PDF di: {PDF_FOLDER}")
        print("Taruh file PDF jurnal ke folder tersebut, lalu jalankan ulang script ini.")
        return

    print(f"Ditemukan {len(pdf_files)} file PDF di {PDF_FOLDER}")
    print("=" * 60)

    # Load existing dataset
    if os.path.exists(DATASET_PATH):
        df = pd.read_csv(DATASET_PATH)
        print(f"Dataset existing: {len(df)} rows")
    else:
        df = pd.DataFrame(columns=[TEXT_COLUMN, SUMMARY_COLUMN])
        print("Dataset baru akan dibuat.")

    # Track processed files
    processed_log = os.path.join(PDF_FOLDER, ".processed.txt")
    if os.path.exists(processed_log):
        with open(processed_log, "r") as f:
            already_processed = set(f.read().strip().split("\n"))
    else:
        already_processed = set()

    new_count = 0
    skip_count = 0
    error_count = 0

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)

        # Skip jika sudah pernah diproses
        if filename in already_processed:
            print(f"  SKIP (sudah ada): {filename}")
            skip_count += 1
            continue

        print(f"\n  Processing: {filename}")

        try:
            # 1. Extract text dari PDF
            raw_text = extract_pdf_text(pdf_path)
            if not raw_text.strip():
                print(f"    ERROR: Tidak bisa extract text (mungkin PDF scan/gambar)")
                error_count += 1
                continue

            # 2. Clean text
            cleaned_text = clean_pdf_text(raw_text)

            # 3. Pisahkan abstrak
            abstract, full_text = extract_abstract(cleaned_text)

            # 4. Validasi
            if len(full_text) < 200:
                print(f"    WARNING: Text terlalu pendek ({len(full_text)} chars), skip")
                error_count += 1
                continue

            if len(abstract) < 50:
                print(f"    WARNING: Abstrak terlalu pendek ({len(abstract)} chars), pakai fallback")

            # 5. Tambah ke dataframe
            new_row = pd.DataFrame([{TEXT_COLUMN: full_text, SUMMARY_COLUMN: abstract}])
            df = pd.concat([df, new_row], ignore_index=True)
            new_count += 1

            # 6. Catat sebagai sudah diproses
            already_processed.add(filename)

            print(f"    OK! full_text: {len(full_text)} chars, summary: {len(abstract)} chars")

        except Exception as e:
            print(f"    ERROR: {e}")
            error_count += 1

    # Save dataset
    if new_count > 0:
        df.to_csv(DATASET_PATH, index=False)

        # Save processed log
        with open(processed_log, "w") as f:
            f.write("\n".join(sorted(already_processed)))

    # Summary
    print("\n" + "=" * 60)
    print(f"SELESAI!")
    print(f"  Baru ditambahkan : {new_count} jurnal")
    print(f"  Di-skip (duplikat): {skip_count}")
    print(f"  Error             : {error_count}")
    print(f"  Total dataset     : {len(df)} rows")
    print(f"  File              : {DATASET_PATH}")


if __name__ == "__main__":
    main()
