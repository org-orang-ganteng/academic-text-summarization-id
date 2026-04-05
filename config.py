# -*- coding: utf-8 -*-
"""
Configuration module for the NLP Summarization Pipeline.

All configurable parameters and hyperparameters are centralized here.
"""

import os

# =============================================================================
# Project Paths
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
RAW_DATA_DIR = os.path.join(DATA_DIR, "raw")
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, "processed")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SUMMARIES_DIR = os.path.join(OUTPUT_DIR, "summaries")
RESULTS_DIR = os.path.join(OUTPUT_DIR, "results")
MODEL_CHECKPOINT_DIR = os.path.join(OUTPUT_DIR, "checkpoints")

# =============================================================================
# Dataset Configuration
# =============================================================================
DATASET_PATH = os.path.join(
    RAW_DATA_DIR, "dataset.csv"
)  # Path to dataset file (CSV or JSON)
TEXT_COLUMN = "full_text"  # Column name for full document text
SUMMARY_COLUMN = "summary"  # Column name for ground truth summary
MAX_INPUT_LENGTH = 10000  # Maximum input text length in characters

# Dataset split ratios
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
TEST_RATIO = 0.1

# =============================================================================
# Preprocessing Configuration
# =============================================================================
CUSTOM_STOPWORDS = []  # Additional stopwords to remove (list of strings)

# =============================================================================
# Extractive Summarization Configuration
# =============================================================================
NUM_EXTRACTIVE_SENTENCES = 5  # Number of sentences to extract for summary
TFIDF_MAX_FEATURES = 5000  # Maximum number of TF-IDF features

# =============================================================================
# Abstractive Summarization Configuration
# =============================================================================
# Model options:
#   - "csebuetnlp/mT5_multilingual_XLSum-small" (fine-tuned for summarization, supports Indonesian)
#   - "google/mt5-small" (raw pre-trained, needs fine-tuning first)
#   - "LazarusNLP/IndoNanoT5-base" (Indonesian T5)
ABSTRACTIVE_MODEL_NAME = "csebuetnlp/mT5_multilingual_XLSum"
MAX_SOURCE_LENGTH = 512  # Max tokens for input text (tokenizer)
MAX_TARGET_LENGTH = 128  # Max tokens for generated summary
NUM_BEAMS = 4  # Number of beams for beam search decoding
BATCH_SIZE = 4  # Batch size for training and inference
NUM_EPOCHS = 3  # Number of fine-tuning epochs
LEARNING_RATE = 5e-5  # Learning rate for fine-tuning
WEIGHT_DECAY = 0.01  # Weight decay for optimizer
WARMUP_STEPS = 100  # Warmup steps for learning rate scheduler
GRADIENT_ACCUMULATION_STEPS = 2  # Gradient accumulation steps
FP16 = False  # Use mixed precision training (requires GPU)

# =============================================================================
# Evaluation Configuration
# =============================================================================
ROUGE_METRICS = ["rouge1", "rouge2", "rougeL"]  # ROUGE metric types to compute

# =============================================================================
# General Configuration
# =============================================================================
RANDOM_SEED = 42  # Random seed for reproducibility
LOG_LEVEL = "INFO"  # Logging level: DEBUG, INFO, WARNING, ERROR


# =============================================================================
# Ensure output directories exist
# =============================================================================
for directory in [
    RAW_DATA_DIR,
    PROCESSED_DATA_DIR,
    SUMMARIES_DIR,
    RESULTS_DIR,
    MODEL_CHECKPOINT_DIR,
]:
    os.makedirs(directory, exist_ok=True)


if __name__ == "__main__":
    """Print all configuration values when run directly."""
    import json

    config_dict = {
        key: value
        for key, value in globals().items()
        if key.isupper() and not key.startswith("_")
    }
    # Convert non-serializable values to strings
    for key, value in config_dict.items():
        if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
            config_dict[key] = str(value)

    print("=" * 50)
    print("  NLP SUMMARIZATION PIPELINE CONFIGURATION")
    print("=" * 50)
    for key, value in sorted(config_dict.items()):
        print(f"  {key}: {value}")
    print("=" * 50)
