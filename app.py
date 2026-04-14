# -*- coding: utf-8 -*-
"""
Flask Web Application for NLP Summarization Pipeline.

Provides a web interface to upload documents, run preprocessing,
extractive/abstractive summarization, and ROUGE evaluation.
"""

import os
import sys
import json
import logging
import traceback
import tempfile
import time
from typing import Dict, List, Optional

import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS

import config
from src.utils import set_seed
from src.preprocessor import TextPreprocessor
from src.extractive_model import ExtractiveSummarizer
from src.evaluator import Evaluator

logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload
app.config["UPLOAD_FOLDER"] = tempfile.mkdtemp()

ALLOWED_EXTENSIONS = {"csv", "json"}

set_seed(config.RANDOM_SEED)

preprocessor = TextPreprocessor()
extractive_summarizer = ExtractiveSummarizer()
evaluator = Evaluator()

# Lazy-load abstractive summarizer (heavy model)
_abstractive_summarizer = None

# Pre-computed JSON cache
_precomputed_cache = {}
PRECOMPUTED_DIR = config.RESULTS_DIR


def _load_precomputed(filename):
    """Load pre-computed JSON results if available."""
    if filename in _precomputed_cache:
        return _precomputed_cache[filename]
    path = os.path.join(PRECOMPUTED_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _precomputed_cache[filename] = data
            logger.info("Loaded pre-computed results from %s", path)
            return data
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)
    return None


def get_abstractive_summarizer():
    """Lazy-load the abstractive summarizer to avoid slow startup."""
    global _abstractive_summarizer
    if _abstractive_summarizer is None:
        try:
            from src.abstractive_model import AbstractiveSummarizer
            _abstractive_summarizer = AbstractiveSummarizer()
            checkpoint_path = os.path.join(config.MODEL_CHECKPOINT_DIR, "best_model")
            if os.path.exists(checkpoint_path):
                _abstractive_summarizer._load_checkpoint(checkpoint_path)
            else:
                _abstractive_summarizer._load_model()
        except Exception as e:
            logger.warning("Could not load abstractive model: %s", e)
            return None
    return _abstractive_summarizer


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


import re

def _clean_pdf_text(text: str) -> str:
    """Clean common PDF extraction artifacts from text."""
    lines = text.split('\n')

    # Detect repeated header/footer lines (appear 3+ times = page header/footer)
    line_counts = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 3:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1
    repeated_lines = {l for l, c in line_counts.items() if c >= 3}

    # Filter lines
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip repeated page headers/footers
        if stripped in repeated_lines:
            continue
        # Skip standalone page numbers
        if re.match(r'^\s*\d{1,4}\s*$', line):
            continue
        # Skip journal citation header, e.g. "JURNAL NAME, (2024), 2(1): 41-48"
        if re.search(r'\(\d{4}\)\s*,?\s*\d+\s*\(\d+\)\s*:\s*\d+', stripped):
            continue
        # Skip DOI lines
        if re.match(r'^\s*(https?://)?doi\.org\s*/\s*\S+', stripped, re.I):
            continue
        # Skip ISSN/DOI-only lines
        if re.match(r'^\s*(e-?issn|p-?issn|issn|doi)\s*[:/]\s*\S+', stripped, re.I):
            continue
        # Skip standalone URLs
        if re.match(r'^\s*https?://\S+\s*$', line):
            continue
        # Skip email lines (lines that are only email addresses)
        if re.match(r'^\s*\*?\s*\S+@\S+\.\S+\s*$', line):
            continue
        # Skip "Volume X – Issue Y – YYYY" footer lines
        if re.match(r'^\s*volume\s+\d+\s*[–—-]\s*issue\s+\d+\s*[–—-]\s*\d{4}\s*$', stripped, re.I):
            continue
        cleaned.append(line)

    text = '\n'.join(cleaned)

    # Remove reference/bibliography section at the end
    text = re.sub(r'(?si)\n\s*(DAFTAR\s+PUSTAKA|REFERENSI|REFERENCES|BIBLIOGRAPHY)\s*\n.*$', '', text)

    # Remove superscript numbers on author names/affiliations
    # e.g. "Chairunnisa1, Ahmad Ari Masyhuri2" -> "Chairunnisa, Ahmad Ari Masyhuri"
    # e.g. "1STKIP Kusumanegara" -> "STKIP Kusumanegara"
    text = re.sub(r'(?<=[a-zA-Z])\d{1,2}(?=[\s,;])', '', text)   # trailing: Name1 -> Name
    text = re.sub(r'(?m)^\s*\d{1,2}(?=[A-Z])', '', text)          # leading: 1STKIP -> STKIP

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# =============================================================================
# Routes
# =============================================================================

@app.route("/")
def index():
    """Serve the main web interface."""
    return render_template("index.html")


@app.route("/api/download-dataset")
def download_dataset():
    """Download the default dataset CSV file."""
    dataset_path = config.DATASET_PATH
    if not os.path.exists(dataset_path):
        return jsonify({"error": "Dataset not found"}), 404
    return send_file(dataset_path, as_attachment=True, download_name="dataset.csv")


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload and validate a CSV/JSON dataset file."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "File type not allowed. Use CSV or JSON."}), 400

        ext = file.filename.rsplit(".", 1)[1].lower()
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], f"upload.{ext}")
        file.save(filepath)

        if ext == "csv":
            df = pd.read_csv(filepath)
        else:
            df = pd.read_json(filepath)

        # Validate columns
        text_col = config.TEXT_COLUMN
        summary_col = config.SUMMARY_COLUMN

        if text_col not in df.columns:
            return jsonify({"error": f"Column '{text_col}' not found. Available: {list(df.columns)}"}), 400
        if summary_col not in df.columns:
            return jsonify({"error": f"Column '{summary_col}' not found. Available: {list(df.columns)}"}), 400

        # Clean
        df = df.dropna(subset=[text_col, summary_col])
        df = df[df[text_col].str.strip().astype(bool)]
        df = df[df[summary_col].str.strip().astype(bool)]

        if len(df) == 0:
            return jsonify({"error": "Dataset is empty after cleaning"}), 400

        texts = df[text_col].tolist()
        summaries = df[summary_col].tolist()

        avg_text_len = sum(len(t) for t in texts) / len(texts)
        avg_summary_len = sum(len(s) for s in summaries) / len(summaries)

        return jsonify({
            "success": True,
            "num_documents": len(texts),
            "texts": texts,
            "summaries": summaries,
            "preview": [
                {"text": t[:200] + "..." if len(t) > 200 else t,
                 "summary": s[:150] + "..." if len(s) > 150 else s}
                for t, s in zip(texts[:5], summaries[:5])
            ],
            "stats": {
                "avg_text_length": round(avg_text_len),
                "avg_summary_length": round(avg_summary_len),
            }
        })

    except Exception as e:
        logger.error("Upload error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload-pdf", methods=["POST"])
def upload_pdf():
    """Upload a single PDF journal and extract its text."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not ("." in file.filename and file.filename.rsplit(".", 1)[1].lower() == "pdf"):
            return jsonify({"error": "File harus berformat PDF"}), 400

        filepath = os.path.join(app.config["UPLOAD_FOLDER"], "upload.pdf")
        file.save(filepath)

        try:
            import fitz  # PyMuPDF
        except ImportError:
            return jsonify({"error": "PyMuPDF belum terinstall. Jalankan: pip install PyMuPDF"}), 500

        doc = fitz.open(filepath)
        pages = []
        full_text_parts = []
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            if text.strip():
                pages.append({"page": page_num + 1, "text": text.strip()})
                full_text_parts.append(text.strip())
        doc.close()

        if not full_text_parts:
            return jsonify({"error": "Tidak dapat mengekstrak teks dari PDF. Pastikan PDF bukan berupa gambar/scan."}), 400

        full_text = "\n\n".join(full_text_parts)

        # Apply PDF text filter
        import re
        full_text = _clean_pdf_text(full_text)

        # Save extracted text to dataset.csv
        dataset_path = config.DATASET_PATH
        new_row = pd.DataFrame([{
            config.TEXT_COLUMN: full_text,
            config.SUMMARY_COLUMN: ""
        }])
        if os.path.exists(dataset_path):
            df_existing = pd.read_csv(dataset_path)
            df_updated = pd.concat([df_existing, new_row], ignore_index=True)
        else:
            df_updated = new_row
        df_updated.to_csv(dataset_path, index=False)
        logger.info("Saved PDF text to %s (total rows: %d)", dataset_path, len(df_updated))

        # Clean up temp file
        try:
            os.remove(filepath)
        except OSError:
            pass

        return jsonify({
            "success": True,
            "filename": file.filename,
            "num_pages": len(pages),
            "text": full_text,
            "text_length": len(full_text),
            "saved_to_dataset": True,
            "dataset_total_rows": len(df_updated),
            "pages": pages[:5],  # Preview first 5 pages
        })

    except Exception as e:
        logger.error("PDF upload error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/preprocess", methods=["POST"])
def preprocess():
    """Run preprocessing step-by-step and return intermediate results."""
    try:
        data = request.get_json()
        texts = data.get("texts", [])

        if not texts:
            return jsonify({"error": "No texts provided"}), 400

        use_cache = data.get("use_cache", False)

        # Check for pre-computed results only when using default dataset
        if use_cache:
            precomputed = _load_precomputed("preprocess.json")
            if precomputed and len(precomputed.get("results", [])) == len(texts):
                time.sleep(1.5)  # Simulated processing delay
                return jsonify(precomputed)

        results = []
        for text in texts:
            original = text

            # Step 1: Case folding
            step1 = preprocessor.case_folding(text)

            # Step 2: Cleaning
            step2 = preprocessor.clean_text(step1)

            # Step 3: Sentence tokenization
            step3 = preprocessor.sentence_tokenize(step2)

            # Step 4: Word tokenization (on full cleaned text)
            step4 = preprocessor.word_tokenize(step2)

            # Step 5: Stopword removal
            step5 = preprocessor.remove_stopwords(step4)

            # Step 6: Stemming
            step6 = preprocessor.stem_tokens(step5)

            results.append({
                "original": original,
                "case_folding": step1,
                "cleaning": step2,
                "sentences": step3,
                "word_tokens": step4,
                "after_stopword_removal": step5,
                "after_stemming": step6,
                "num_sentences": len(step3),
                "num_tokens_before": len(step4),
                "num_tokens_after": len(step5),
                "num_tokens_stemmed": len(step6),
            })

        return jsonify({"success": True, "results": results})

    except Exception as e:
        logger.error("Preprocess error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/summarize", methods=["POST"])
def summarize():
    """Run extractive and abstractive summarization with detailed steps."""
    try:
        data = request.get_json()
        texts = data.get("texts", [])

        if not texts:
            return jsonify({"error": "No texts provided"}), 400

        use_cache = data.get("use_cache", False)

        # Check for pre-computed results only when using default dataset
        if use_cache:
            precomputed = _load_precomputed("summarize.json")
            if precomputed and len(precomputed.get("extractive", [])) == len(texts):
                time.sleep(2.0)  # Simulated processing delay
                return jsonify(precomputed)

        result = {"success": True}

        # Extractive with detailed steps
        try:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity as cos_sim

            ext_summaries = []
            ext_details = []

            for text in texts:
                detail = {}

                # Step 1: Sentence extraction
                sentences = extractive_summarizer._get_sentences(text)
                detail["sentences"] = sentences
                detail["num_sentences"] = len(sentences)

                if not sentences:
                    ext_summaries.append("")
                    ext_details.append(detail)
                    continue

                n_target = extractive_summarizer.num_sentences
                if len(sentences) <= n_target:
                    summary = " ".join(sentences)
                    ext_summaries.append(summary)
                    detail["summary"] = summary
                    detail["note"] = "Jumlah kalimat kurang dari target"
                    ext_details.append(detail)
                    continue

                # Step 2: TF-IDF
                try:
                    tfidf_matrix = extractive_summarizer._build_tfidf_matrix(sentences)
                    detail["tfidf_shape"] = [int(tfidf_matrix.shape[0]), int(tfidf_matrix.shape[1])]
                    detail["num_features"] = int(tfidf_matrix.shape[1])
                except ValueError:
                    summary = " ".join(sentences[:n_target])
                    ext_summaries.append(summary)
                    detail["tfidf_error"] = "Gagal membangun TF-IDF"
                    ext_details.append(detail)
                    continue

                # Step 3: Cosine similarity
                sim_matrix = cos_sim(tfidf_matrix)
                n = len(sentences)
                upper_vals = sim_matrix[np.triu_indices(n, k=1)]
                detail["avg_similarity"] = round(float(np.mean(upper_vals)), 4) if len(upper_vals) > 0 else 0
                detail["max_similarity"] = round(float(np.max(upper_vals)), 4) if len(upper_vals) > 0 else 0
                pairs = []
                for i_idx in range(min(n, 20)):
                    for j_idx in range(i_idx + 1, min(n, 20)):
                        pairs.append({
                            "i": i_idx, "j": j_idx,
                            "sim": round(float(sim_matrix[i_idx][j_idx]), 4)
                        })
                pairs.sort(key=lambda x: x["sim"], reverse=True)
                detail["top_pairs"] = pairs[:8]

                # Step 4: PageRank
                graph = extractive_summarizer._build_similarity_graph(tfidf_matrix)
                scores = extractive_summarizer._rank_sentences(graph)

                ranked_indices = sorted(scores, key=scores.get, reverse=True)
                top_indices = sorted(ranked_indices[:n_target])

                sentence_scores = []
                for idx in range(len(sentences)):
                    sentence_scores.append({
                        "index": idx,
                        "sentence": sentences[idx][:200] + ("..." if len(sentences[idx]) > 200 else ""),
                        "score": round(float(scores[idx]), 6),
                        "rank": ranked_indices.index(idx) + 1,
                        "selected": idx in top_indices,
                    })
                detail["sentence_scores"] = sentence_scores
                detail["selected_indices"] = [int(i) for i in top_indices]
                detail["num_selected"] = len(top_indices)

                # Final summary
                summary = " ".join([sentences[i] for i in top_indices])
                ext_summaries.append(summary)
                detail["summary"] = summary
                ext_details.append(detail)

            result["extractive"] = ext_summaries
            result["extractive_details"] = ext_details
        except Exception as e:
            logger.error("Extractive error: %s", traceback.format_exc())
            result["extractive"] = None
            result["extractive_error"] = str(e)

        # Abstractive with model info
        try:
            abs_model = get_abstractive_summarizer()
            if abs_model is not None:
                abs_summaries = abs_model.batch_summarize(texts)
                result["abstractive"] = abs_summaries
                result["abstractive_details"] = {
                    "model_name": abs_model.model_name,
                    "device": str(abs_model.device),
                    "max_source_length": abs_model.max_source_length,
                    "max_target_length": abs_model.max_target_length,
                    "num_beams": abs_model.num_beams,
                    "num_parameters": f"{sum(p.numel() for p in abs_model.model.parameters()):,}" if abs_model.model else "N/A",
                }
            else:
                result["abstractive"] = None
                result["abstractive_error"] = (
                    "Model abstractive belum tersedia. "
                    "Jalankan training terlebih dahulu dengan: python main.py --mode train --model abstractive"
                )
        except Exception as e:
            logger.error("Abstractive error: %s", traceback.format_exc())
            result["abstractive"] = None
            result["abstractive_error"] = str(e)

        return jsonify(result)

    except Exception as e:
        logger.error("Summarize error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    """Run ROUGE evaluation on predictions vs references."""
    try:
        data = request.get_json()
        references = data.get("references", [])
        extractive_preds = data.get("extractive_preds")
        abstractive_preds = data.get("abstractive_preds")

        if not references:
            return jsonify({"error": "No reference summaries provided"}), 400

        use_cache = data.get("use_cache", False)

        # Check for pre-computed results only when using default dataset
        if use_cache:
            precomputed = _load_precomputed("evaluate.json")
            if precomputed and len(precomputed.get("per_document", [])) == len(references):
                time.sleep(1.0)  # Simulated processing delay
                return jsonify(precomputed)

        result = {"success": True}

        ext_scores = None
        abs_scores = None

        if extractive_preds:
            ext_scores = evaluator.compute_rouge(extractive_preds, references)
            result["extractive_scores"] = ext_scores

        if abstractive_preds:
            abs_scores = evaluator.compute_rouge(abstractive_preds, references)
            result["abstractive_scores"] = abs_scores

        # Per-document ROUGE scores
        per_document = []
        for i in range(len(references)):
            doc = {"doc_id": i, "reference_preview": references[i][:150]}

            if extractive_preds and i < len(extractive_preds):
                doc["extractive_preview"] = extractive_preds[i][:150]
                sc = evaluator.scorer.score(references[i], extractive_preds[i])
                doc["ext"] = {
                    m: {
                        "p": round(sc[m].precision, 4),
                        "r": round(sc[m].recall, 4),
                        "f": round(sc[m].fmeasure, 4),
                    }
                    for m in config.ROUGE_METRICS
                }

            if abstractive_preds and i < len(abstractive_preds):
                doc["abstractive_preview"] = abstractive_preds[i][:150]
                sc = evaluator.scorer.score(references[i], abstractive_preds[i])
                doc["abs"] = {
                    m: {
                        "p": round(sc[m].precision, 4),
                        "r": round(sc[m].recall, 4),
                        "f": round(sc[m].fmeasure, 4),
                    }
                    for m in config.ROUGE_METRICS
                }

            per_document.append(doc)

        result["per_document"] = per_document

        # Determine best method
        ext_avg = None
        abs_avg = None
        if extractive_preds and ext_scores:
            ext_avg = sum(
                ext_scores[m]["fmeasure"] for m in config.ROUGE_METRICS
            ) / len(config.ROUGE_METRICS)
            result["extractive_avg_f1"] = round(ext_avg, 4)
        if abstractive_preds and abs_scores:
            abs_avg = sum(
                abs_scores[m]["fmeasure"] for m in config.ROUGE_METRICS
            ) / len(config.ROUGE_METRICS)
            result["abstractive_avg_f1"] = round(abs_avg, 4)

        # Find best among available methods
        methods = {}
        if ext_avg is not None:
            methods["Extractive"] = ext_avg
        if abs_avg is not None:
            methods["Abstractive"] = abs_avg
        if methods:
            result["best_method"] = max(methods, key=methods.get)

        return jsonify(result)

    except Exception as e:
        logger.error("Evaluate error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/load-default", methods=["GET", "POST"])
def load_default_dataset():
    """Load the default dataset from data/raw/dataset.csv."""
    try:
        # Check for pre-computed dataset
        precomputed = _load_precomputed("dataset.json")
        if precomputed:
            return jsonify(precomputed)

        dataset_path = config.DATASET_PATH
        if not os.path.exists(dataset_path):
            return jsonify({"error": "Default dataset not found at " + dataset_path}), 404

        df = pd.read_csv(dataset_path)
        text_col = config.TEXT_COLUMN
        summary_col = config.SUMMARY_COLUMN

        if text_col not in df.columns or summary_col not in df.columns:
            return jsonify({"error": f"Dataset must have '{text_col}' and '{summary_col}' columns"}), 400

        df = df.dropna(subset=[text_col, summary_col])
        df = df[df[text_col].str.strip().astype(bool)]
        df = df[df[summary_col].str.strip().astype(bool)]

        if len(df) == 0:
            return jsonify({"error": "Dataset is empty after cleaning"}), 400

        texts = df[text_col].tolist()
        summaries = df[summary_col].tolist()

        avg_text_len = sum(len(str(t)) for t in texts) / len(texts)
        avg_summary_len = sum(len(str(s)) for s in summaries) / len(summaries)

        return jsonify({
            "success": True,
            "num_documents": len(texts),
            "texts": texts,
            "summaries": summaries,
            "preview": [
                {"text": str(t)[:200] + "..." if len(str(t)) > 200 else str(t),
                 "summary": str(s)[:150] + "..." if len(str(s)) > 150 else str(s)}
                for t, s in zip(texts[:5], summaries[:5])
            ],
            "stats": {
                "avg_text_length": round(avg_text_len),
                "avg_summary_length": round(avg_summary_len),
            }
        })
    except Exception as e:
        logger.error("Load default error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/process-text", methods=["POST"])
def process_single_text():
    """Process a single text through the full pipeline."""
    try:
        data = request.get_json()
        text = data.get("text", "").strip()
        reference = data.get("reference", "").strip()

        if not text:
            return jsonify({"error": "No text provided"}), 400

        result = {"success": True}

        # Step 1: Preprocessing
        step1 = preprocessor.case_folding(text)
        step2 = preprocessor.clean_text(step1)
        step3 = preprocessor.sentence_tokenize(step2)
        step4 = preprocessor.word_tokenize(step2)
        step5 = preprocessor.remove_stopwords(step4)
        step6 = preprocessor.stem_tokens(step5)

        result["preprocessing"] = {
            "original": text,
            "case_folding": step1,
            "cleaning": step2,
            "sentences": step3,
            "word_tokens": step4,
            "after_stopword_removal": step5,
            "after_stemming": step6,
            "num_sentences": len(step3),
            "num_tokens_before": len(step4),
            "num_tokens_after": len(step5),
            "num_tokens_stemmed": len(step6),
        }

        # Step 2: Summarization
        try:
            ext_summary = extractive_summarizer.summarize(text)
            result["extractive_summary"] = ext_summary
        except Exception as e:
            result["extractive_summary"] = None
            result["extractive_error"] = str(e)

        try:
            abs_model = get_abstractive_summarizer()
            if abs_model is not None:
                abs_summary = abs_model.summarize(text)
                result["abstractive_summary"] = abs_summary
            else:
                result["abstractive_summary"] = None
                result["abstractive_error"] = (
                    "Model abstractive belum tersedia. "
                    "Jalankan training terlebih dahulu."
                )
        except Exception as e:
            result["abstractive_summary"] = None
            result["abstractive_error"] = str(e)

        # Step 3: Evaluation (only if reference is provided)
        if reference:
            preds_ext = [result.get("extractive_summary", "")] if result.get("extractive_summary") else None
            preds_abs = [result.get("abstractive_summary", "")] if result.get("abstractive_summary") else None
            refs = [reference]

            if preds_ext:
                result["extractive_scores"] = evaluator.compute_rouge(preds_ext, refs)
            if preds_abs:
                result["abstractive_scores"] = evaluator.compute_rouge(preds_abs, refs)

            if preds_ext and preds_abs:
                ext_avg = sum(
                    result["extractive_scores"][m]["fmeasure"] for m in config.ROUGE_METRICS
                ) / len(config.ROUGE_METRICS)
                abs_avg = sum(
                    result["abstractive_scores"][m]["fmeasure"] for m in config.ROUGE_METRICS
                ) / len(config.ROUGE_METRICS)
                result["best_method"] = "Extractive" if ext_avg >= abs_avg else "Abstractive"

        return jsonify(result)

    except Exception as e:
        logger.error("Process text error: %s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting NLP Summarization Web App...")
    app.run(debug=True, host="0.0.0.0", port=3000, use_reloader=False, threaded=True)
