# Automatic Text Summarization — Indonesian Academic Documents

Pipeline NLP end-to-end untuk **Automatic Text Summarization** pada dokumen akademik berbahasa Indonesia (skripsi/jurnal). Membandingkan dua pendekatan: **Extractive** (TextRank + TF-IDF) vs **Abstractive** (mT5 / IndoBERT). Tersedia dalam dua mode: **CLI pipeline** dan **Web interface** (Flask).

> Dibuat oleh **devnolife**

---

## Struktur Project

```
.
├── app.py                   # Web application (Flask)
├── config.py                # Konfigurasi dan hyperparameter
├── main.py                  # Entry point CLI pipeline
├── requirements.txt         # Dependencies
├── templates/
│   └── index.html           # Web UI (Tailwind CSS)
├── data/
│   ├── raw/                 # Dataset mentah (CSV/JSON)
│   └── processed/           # Data hasil preprocessing
├── output/
│   ├── summaries/           # Hasil ringkasan
│   ├── results/             # Laporan evaluasi
│   └── checkpoints/         # Model checkpoint
└── src/
    ├── __init__.py
    ├── utils.py             # Fungsi helper
    ├── data_loader.py       # Loading & validasi dataset
    ├── preprocessor.py      # Pipeline preprocessing NLP
    ├── extractive_model.py  # Summarization TextRank + TF-IDF
    ├── abstractive_model.py # Summarization mT5 / IndoBERT
    └── evaluator.py         # Evaluasi ROUGE
```

---

## Fitur Utama

| Komponen | Deskripsi |
|---|---|
| **Data Loader** | Load CSV/JSON, validasi kolom, cleaning, split 80/10/10 |
| **Preprocessor** | Case folding, cleaning (URL/HTML/email), tokenisasi kalimat & kata, stopword removal (Indonesian), stemming (PySastrawi) |
| **Extractive** | TF-IDF vectorization, cosine similarity graph, PageRank scoring, output urutan asli dokumen. CPU-only |
| **Abstractive** | Fine-tune `google/mt5-small` atau model IndoBERT via HuggingFace `Seq2SeqTrainer`, beam search decoding, auto-load checkpoint |
| **Evaluator** | ROUGE-1, ROUGE-2, ROUGE-L (precision, recall, F1), laporan per-dokumen & agregat, export CSV/JSON |
| **Web App** | Upload dataset, preprocessing step-by-step, summarization, dan evaluasi ROUGE via browser |

---

## Instalasi

```bash
pip install -r requirements.txt
```

Dependencies utama:
- `pandas`, `numpy` — data handling
- `nltk`, `PySastrawi` — preprocessing bahasa Indonesia
- `scikit-learn`, `networkx` — TF-IDF & TextRank
- `transformers`, `torch`, `datasets` — model abstractive
- `sentencepiece`, `protobuf` — tokenizer mT5
- `accelerate` — training optimizer
- `rouge-score` — evaluasi ROUGE
- `flask`, `flask-cors` — web application
- `tqdm` — progress bar

---

## Cara Pakai

### Format Dataset

Siapkan file CSV atau JSON di `data/raw/` dengan minimal dua kolom:

| full_text | summary |
|---|---|
| Isi lengkap dokumen... | Ringkasan referensi... |

### Mode 1: CLI Pipeline

```bash
# Full pipeline (train + evaluate, kedua metode)
python main.py

# Hanya extractive
python main.py --model extractive

# Hanya abstractive
python main.py --model abstractive

# Train model abstractive saja
python main.py --mode train --model abstractive

# Evaluate saja (butuh checkpoint)
python main.py --mode evaluate

# Override path dataset
python main.py --data path/ke/dataset.csv
```

#### CLI Arguments

| Argument | Pilihan | Default | Keterangan |
|---|---|---|---|
| `--mode` | `train`, `evaluate`, `full` | `full` | Mode pipeline |
| `--model` | `extractive`, `abstractive`, `both` | `both` | Metode yang dijalankan |
| `--data` | path ke file | dari `config.py` | Override path dataset |

### Mode 2: Web Interface

```bash
python app.py
```

Buka browser di `http://localhost:5000`. Web UI menyediakan:

- **Upload Dataset** — upload file CSV/JSON, validasi otomatis
- **Preprocessing** — lihat hasil setiap step (case folding, cleaning, tokenisasi, stopword removal, stemming)
- **Summarization** — jalankan extractive & abstractive summarization
- **Evaluation** — hitung skor ROUGE dan lihat perbandingan metode
- **Single Text** — proses satu teks langsung (tanpa upload dataset)

#### API Endpoints

| Endpoint | Method | Deskripsi |
|---|---|---|
| `/` | GET | Halaman utama web UI |
| `/api/upload` | POST | Upload dan validasi dataset (CSV/JSON) |
| `/api/preprocess` | POST | Preprocessing step-by-step |
| `/api/summarize` | POST | Extractive & abstractive summarization |
| `/api/evaluate` | POST | Evaluasi ROUGE |
| `/api/process-text` | POST | Proses single text (preprocess + summarize + evaluate) |

---

## Konfigurasi

Semua parameter ada di `config.py`:

```python
# Dataset
DATASET_PATH = "data/raw/dataset.csv"
TEXT_COLUMN = "full_text"
SUMMARY_COLUMN = "summary"
MAX_INPUT_LENGTH = 10000

# Split ratio
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
TEST_RATIO = 0.1

# Extractive
NUM_EXTRACTIVE_SENTENCES = 5
TFIDF_MAX_FEATURES = 5000

# Abstractive
ABSTRACTIVE_MODEL_NAME = "google/mt5-small"
MAX_SOURCE_LENGTH = 512
MAX_TARGET_LENGTH = 128
NUM_BEAMS = 4
BATCH_SIZE = 4
NUM_EPOCHS = 3
LEARNING_RATE = 5e-5
WEIGHT_DECAY = 0.01
WARMUP_STEPS = 100
GRADIENT_ACCUMULATION_STEPS = 2
FP16 = False

# Evaluation
ROUGE_METRICS = ["rouge1", "rouge2", "rougeL"]

# General
RANDOM_SEED = 42
LOG_LEVEL = "INFO"
```

---

## Output

### Console (CLI)

```
================================================
  TEXT SUMMARIZATION EVALUATION REPORT
================================================
Method              ROUGE-1   ROUGE-2   ROUGE-L
------------------------------------------------
Extractive           0.XXXX    0.XXXX    0.XXXX
Abstractive          0.XXXX    0.XXXX    0.XXXX
------------------------------------------------
Best Method:                      [Extractive / Abstractive]
================================================
```

### File Output

| File | Keterangan |
|---|---|
| `output/summaries/extractive_summaries.csv` | Hasil extractive |
| `output/summaries/abstractive_summaries.csv` | Hasil abstractive |
| `output/results/evaluation_report.csv` | Skor ROUGE per dokumen |
| `output/results/comparison_summary.json` | Perbandingan agregat |
| `output/checkpoints/best_model/` | Checkpoint model abstractive |

---

## Testing Per Modul

Setiap modul bisa dijalankan secara independen untuk testing:

```bash
python -m src.utils
python -m src.data_loader
python -m src.preprocessor
python -m src.extractive_model
python -m src.abstractive_model
python -m src.evaluator
python config.py
```

---

## Author

**devnolife**
