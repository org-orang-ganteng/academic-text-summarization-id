# -*- coding: utf-8 -*-
"""
Dataset Loader module for the NLP Summarization Pipeline.

Handles loading, validating, splitting, and reporting statistics
for Indonesian academic document datasets.
"""

import logging
import os
import sys
from typing import Optional, Tuple

import pandas as pd

# Add parent directory to path for imports when running standalone
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from src.utils import compute_text_stats, truncate_text

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Dataset loader for Indonesian academic document summarization.

    Handles loading from CSV/JSON, validation, cleaning, splitting,
    and statistics reporting.

    Attributes:
        dataset_path: Path to the dataset file.
        text_column: Column name containing the full document text.
        summary_column: Column name containing the ground truth summary.
        max_input_length: Maximum character length for input text.
        train_ratio: Proportion of data for training set.
        val_ratio: Proportion of data for validation set.
        test_ratio: Proportion of data for test set.
    """

    def __init__(
        self,
        dataset_path: Optional[str] = None,
        text_column: Optional[str] = None,
        summary_column: Optional[str] = None,
        max_input_length: Optional[int] = None,
        train_ratio: Optional[float] = None,
        val_ratio: Optional[float] = None,
        test_ratio: Optional[float] = None,
    ) -> None:
        """
        Initialize the DataLoader with configuration parameters.

        Args:
            dataset_path: Path to dataset file. Defaults to config value.
            text_column: Column for full text. Defaults to config value.
            summary_column: Column for summary. Defaults to config value.
            max_input_length: Max chars for input text. Defaults to config value.
            train_ratio: Training split ratio. Defaults to config value.
            val_ratio: Validation split ratio. Defaults to config value.
            test_ratio: Test split ratio. Defaults to config value.
        """
        self.dataset_path = dataset_path or config.DATASET_PATH
        self.text_column = text_column or config.TEXT_COLUMN
        self.summary_column = summary_column or config.SUMMARY_COLUMN
        self.max_input_length = max_input_length or config.MAX_INPUT_LENGTH
        self.train_ratio = train_ratio or config.TRAIN_RATIO
        self.val_ratio = val_ratio or config.VAL_RATIO
        self.test_ratio = test_ratio or config.TEST_RATIO

        logger.info("DataLoader initialized with dataset: %s", self.dataset_path)

    def load_dataset(self) -> pd.DataFrame:
        """
        Load dataset from CSV or JSON file.

        Returns:
            DataFrame containing the loaded dataset.

        Raises:
            FileNotFoundError: If the dataset file does not exist.
            ValueError: If the file format is not supported.
        """
        if not os.path.exists(self.dataset_path):
            logger.error("Dataset file not found: %s", self.dataset_path)
            raise FileNotFoundError(f"Dataset file not found: {self.dataset_path}")

        file_ext = os.path.splitext(self.dataset_path)[1].lower()

        if file_ext == ".csv":
            df = pd.read_csv(self.dataset_path)
            logger.info("Loaded CSV dataset with %d rows", len(df))
        elif file_ext == ".json":
            df = pd.read_json(self.dataset_path)
            logger.info("Loaded JSON dataset with %d rows", len(df))
        else:
            raise ValueError(f"Unsupported file format '{file_ext}'. Use CSV or JSON.")

        return df

    def validate_columns(self, df: pd.DataFrame) -> None:
        """
        Validate that required columns exist in the DataFrame.

        Args:
            df: DataFrame to validate.

        Raises:
            ValueError: If required columns are missing.
        """
        required_columns = [self.text_column, self.summary_column]
        missing = [col for col in required_columns if col not in df.columns]

        if missing:
            available = list(df.columns)
            logger.error(
                "Missing required columns: %s. Available columns: %s",
                missing,
                available,
            )
            raise ValueError(
                f"Missing required columns: {missing}. Available columns: {available}"
            )

        logger.info("Column validation passed. Required columns found.")

    def clean_dataset(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean the dataset by removing rows with empty or null text/summary.

        Args:
            df: DataFrame to clean.

        Returns:
            Cleaned DataFrame with invalid rows removed.
        """
        initial_count = len(df)

        # Remove rows where text or summary is null
        df = df.dropna(subset=[self.text_column, self.summary_column])

        # Remove rows where text or summary is empty string
        mask_text = df[self.text_column].astype(str).str.strip().str.len() > 0
        mask_summary = df[self.summary_column].astype(str).str.strip().str.len() > 0
        df = df.loc[mask_text & mask_summary]

        # Ensure text columns are strings
        df[self.text_column] = df[self.text_column].astype(str)
        df[self.summary_column] = df[self.summary_column].astype(str)

        removed_count = initial_count - len(df)
        if removed_count > 0:
            logger.warning(
                "Removed %d rows with empty/null text or summary", removed_count
            )
        else:
            logger.info("No rows removed during cleaning")

        df = df.reset_index(drop=True)
        return df

    def truncate_texts(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Truncate full_text column to maximum character length.

        Args:
            df: DataFrame with text column to truncate.

        Returns:
            DataFrame with truncated text column.
        """
        truncated_count = 0
        original_lengths = df[self.text_column].str.len()

        df[self.text_column] = df[self.text_column].apply(
            lambda x: truncate_text(x, self.max_input_length)
        )

        new_lengths = df[self.text_column].str.len()
        truncated_count = (original_lengths > new_lengths).sum()

        if truncated_count > 0:
            logger.info(
                "Truncated %d texts to max %d characters",
                truncated_count,
                self.max_input_length,
            )
        return df

    def split_dataset(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Split dataset into train, validation, and test sets.

        Args:
            df: DataFrame to split.

        Returns:
            Tuple of (train_df, val_df, test_df) DataFrames.
        """
        # Shuffle the dataset
        df = df.sample(frac=1, random_state=config.RANDOM_SEED).reset_index(drop=True)

        n = len(df)
        train_end = int(n * self.train_ratio)
        val_end = train_end + int(n * self.val_ratio)

        # Ensure each split has at least 1 sample when dataset is small
        if n >= 3:
            # Need at least 1 for val and 1 for test
            if train_end > n - 2:
                train_end = n - 2
            if val_end <= train_end:
                val_end = train_end + 1

        train_df = df.iloc[:train_end].reset_index(drop=True)
        val_df = df.iloc[train_end:val_end].reset_index(drop=True)
        test_df = df.iloc[val_end:].reset_index(drop=True)

        logger.info(
            "Dataset split — Train: %d, Validation: %d, Test: %d",
            len(train_df),
            len(val_df),
            len(test_df),
        )
        return train_df, val_df, test_df

    def log_statistics(self, df: pd.DataFrame, split_name: str = "Full") -> None:
        """
        Log dataset statistics including document count and text lengths.

        Args:
            df: DataFrame to compute statistics for.
            split_name: Name of the dataset split for logging.
        """
        text_stats = compute_text_stats(df[self.text_column].tolist())
        summary_stats = compute_text_stats(df[self.summary_column].tolist())

        logger.info("=" * 50)
        logger.info("  Dataset Statistics [%s]", split_name)
        logger.info("=" * 50)
        logger.info("  Total documents: %d", text_stats["count"])
        logger.info(
            "  Full text — Avg: %.1f, Min: %d, Max: %d chars",
            text_stats["avg_length"],
            text_stats["min_length"],
            text_stats["max_length"],
        )
        logger.info(
            "  Summary   — Avg: %.1f, Min: %d, Max: %d chars",
            summary_stats["avg_length"],
            summary_stats["min_length"],
            summary_stats["max_length"],
        )
        logger.info("=" * 50)

    def load_and_prepare(
        self,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Execute the full data loading pipeline.

        Loads, validates, cleans, truncates, logs statistics, and splits
        the dataset in a single call.

        Returns:
            Tuple of (train_df, val_df, test_df) DataFrames.
        """
        logger.info("Starting data loading pipeline...")

        # Step 1: Load dataset
        df = self.load_dataset()

        # Step 2: Validate columns
        self.validate_columns(df)

        # Step 3: Clean dataset
        df = self.clean_dataset(df)

        # Step 4: Truncate texts
        df = self.truncate_texts(df)

        # Step 5: Log full dataset statistics
        self.log_statistics(df, split_name="Full Dataset")

        # Step 6: Split dataset
        train_df, val_df, test_df = self.split_dataset(df)

        # Step 7: Log split statistics
        self.log_statistics(train_df, split_name="Train")
        self.log_statistics(val_df, split_name="Validation")
        self.log_statistics(test_df, split_name="Test")

        logger.info("Data loading pipeline completed successfully.")
        return train_df, val_df, test_df


if __name__ == "__main__":
    """Test the DataLoader when run directly."""
    from src.utils import setup_logging

    setup_logging("DEBUG")

    # Create a sample dataset for testing
    sample_data = {
        "full_text": [
            "Penelitian ini bertujuan untuk menganalisis pengaruh media sosial terhadap prestasi akademik mahasiswa. "
            "Metode yang digunakan adalah survei kuantitatif dengan sampel 200 mahasiswa dari berbagai fakultas. "
            "Hasil penelitian menunjukkan bahwa terdapat korelasi negatif antara durasi penggunaan media sosial "
            "dengan indeks prestasi kumulatif mahasiswa.",
            "Skripsi ini membahas implementasi algoritma machine learning untuk klasifikasi sentimen pada ulasan "
            "produk berbahasa Indonesia. Dataset yang digunakan terdiri dari 10.000 ulasan dari platform e-commerce. "
            "Model yang diuji meliputi Naive Bayes, SVM, dan Random Forest.",
            "Penelitian ini mengkaji efektivitas pembelajaran daring selama pandemi COVID-19 terhadap motivasi "
            "belajar mahasiswa program studi Teknik Informatika.",
        ],
        "summary": [
            "Penelitian ini menunjukkan korelasi negatif antara penggunaan media sosial dan prestasi akademik mahasiswa.",
            "Implementasi machine learning untuk klasifikasi sentimen ulasan produk Indonesia menggunakan tiga model.",
            "Kajian efektivitas pembelajaran daring terhadap motivasi belajar mahasiswa Teknik Informatika.",
        ],
    }

    sample_df = pd.DataFrame(sample_data)
    sample_path = os.path.join(config.RAW_DATA_DIR, "sample_dataset.csv")
    sample_df.to_csv(sample_path, index=False)
    logger.info("Sample dataset saved to: %s", sample_path)

    # Test the loader
    loader = DataLoader(dataset_path=sample_path)
    train_df, val_df, test_df = loader.load_and_prepare()

    print(f"\nTrain set size: {len(train_df)}")
    print(f"Validation set size: {len(val_df)}")
    print(f"Test set size: {len(test_df)}")
    print("\nDataLoader module test completed successfully.")
