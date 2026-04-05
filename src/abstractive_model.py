# -*- coding: utf-8 -*-
"""
Abstractive Summarization module using transformer-based models.

Supports fine-tuning and inference with HuggingFace models such as
mT5 and IndoBERT-based seq2seq models for Indonesian text summarization.
"""

import logging
import os
import sys
from typing import Dict, List, Optional

import torch
from torch.utils.data import Dataset

# Add parent directory to path for imports when running standalone
if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

logger = logging.getLogger(__name__)


class SummarizationDataset(Dataset):
    """
    PyTorch Dataset for text summarization tasks.

    Tokenizes input texts and target summaries for seq2seq model training.

    Attributes:
        encodings: Tokenized input sequences.
        labels: Tokenized target sequences.
    """

    def __init__(
        self,
        texts: List[str],
        summaries: List[str],
        tokenizer,
        max_source_length: int,
        max_target_length: int,
    ) -> None:
        """
        Initialize the SummarizationDataset.

        Args:
            texts: List of input document strings.
            summaries: List of target summary strings.
            tokenizer: HuggingFace tokenizer instance.
            max_source_length: Maximum token length for input.
            max_target_length: Maximum token length for target.
        """
        self.tokenizer = tokenizer
        self.texts = texts
        self.summaries = summaries
        self.max_source_length = max_source_length
        self.max_target_length = max_target_length

    def __len__(self) -> int:
        """Return the number of samples in the dataset."""
        return len(self.texts)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        """
        Get a single tokenized sample.

        Args:
            idx: Sample index.

        Returns:
            Dictionary with input_ids, attention_mask, and labels tensors.
        """
        source = self.texts[idx]
        target = self.summaries[idx]

        # Add task prefix for raw mT5 models (not needed for fine-tuned XLSum)
        if "mt5" in config.ABSTRACTIVE_MODEL_NAME.lower() and "xlsum" not in config.ABSTRACTIVE_MODEL_NAME.lower():
            source = "summarize: " + source

        source_encoding = self.tokenizer(
            source,
            max_length=self.max_source_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        target_encoding = self.tokenizer(
            target,
            max_length=self.max_target_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        labels = target_encoding["input_ids"].squeeze()
        # Replace padding token ids with -100 so they are ignored in loss
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": source_encoding["input_ids"].squeeze(),
            "attention_mask": source_encoding["attention_mask"].squeeze(),
            "labels": labels,
        }


class AbstractiveSummarizer:
    """
    Transformer-based abstractive summarizer with fine-tuning support.

    Supports mT5 and IndoBERT-based seq2seq models loaded from HuggingFace.
    Gracefully falls back to CPU if GPU is not available.

    Attributes:
        model_name: HuggingFace model identifier.
        device: Torch device (cuda or cpu).
        model: Loaded transformer model.
        tokenizer: Loaded tokenizer.
        max_source_length: Maximum input token length.
        max_target_length: Maximum output token length.
        num_beams: Number of beams for beam search.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        max_source_length: Optional[int] = None,
        max_target_length: Optional[int] = None,
        num_beams: Optional[int] = None,
    ) -> None:
        """
        Initialize the AbstractiveSummarizer.

        Args:
            model_name: HuggingFace model name. Defaults to config value.
            max_source_length: Max input tokens. Defaults to config value.
            max_target_length: Max output tokens. Defaults to config value.
            num_beams: Beam search width. Defaults to config value.
        """
        self.model_name = model_name or config.ABSTRACTIVE_MODEL_NAME
        self.max_source_length = max_source_length or config.MAX_SOURCE_LENGTH
        self.max_target_length = max_target_length or config.MAX_TARGET_LENGTH
        self.num_beams = num_beams or config.NUM_BEAMS

        # Determine device — graceful GPU fallback
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            logger.info("Using GPU: %s", torch.cuda.get_device_name(0))
        else:
            self.device = torch.device("cpu")
            logger.info("GPU not available. Using CPU for abstractive model.")

        self.model = None
        self.tokenizer = None

        logger.info(
            "AbstractiveSummarizer initialized — model=%s, device=%s",
            self.model_name,
            self.device,
        )

    def _load_model(self) -> None:
        """
        Load the pre-trained model and tokenizer from HuggingFace.

        Selects the appropriate model class based on the model name.
        """
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

        logger.info("Loading model and tokenizer: %s", self.model_name)

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
            self.model.to(self.device)

            logger.info(
                "Model loaded successfully. Parameters: %s",
                f"{sum(p.numel() for p in self.model.parameters()):,}",
            )
        except Exception as e:
            logger.error("Failed to load model %s: %s", self.model_name, e)
            raise

    def _load_checkpoint(self, checkpoint_path: str) -> bool:
        """
        Load a fine-tuned model checkpoint if it exists.

        Args:
            checkpoint_path: Path to the checkpoint directory.

        Returns:
            True if checkpoint was loaded successfully, False otherwise.
        """
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

        if not os.path.exists(checkpoint_path):
            logger.info("No checkpoint found at: %s", checkpoint_path)
            return False

        try:
            logger.info("Loading fine-tuned checkpoint from: %s", checkpoint_path)
            self.tokenizer = AutoTokenizer.from_pretrained(checkpoint_path)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint_path)
            self.model.to(self.device)
            logger.info("Checkpoint loaded successfully.")
            return True
        except Exception as e:
            logger.warning("Failed to load checkpoint: %s. Will retrain.", e)
            return False

    def fine_tune(
        self,
        train_texts: List[str],
        train_summaries: List[str],
        val_texts: List[str],
        val_summaries: List[str],
    ) -> str:
        """
        Fine-tune the model on the provided training data.

        Uses HuggingFace Seq2SeqTrainer for training with proper
        tokenization, padding, and truncation.

        Args:
            train_texts: List of training document texts.
            train_summaries: List of training summary targets.
            val_texts: List of validation document texts.
            val_summaries: List of validation summary targets.

        Returns:
            Path to the saved model checkpoint directory.
        """
        from transformers import (
            Seq2SeqTrainer,
            Seq2SeqTrainingArguments,
            DataCollatorForSeq2Seq,
        )

        # Load base model if not already loaded
        if self.model is None:
            self._load_model()

        # Create datasets
        train_dataset = SummarizationDataset(
            texts=train_texts,
            summaries=train_summaries,
            tokenizer=self.tokenizer,
            max_source_length=self.max_source_length,
            max_target_length=self.max_target_length,
        )
        val_dataset = SummarizationDataset(
            texts=val_texts,
            summaries=val_summaries,
            tokenizer=self.tokenizer,
            max_source_length=self.max_source_length,
            max_target_length=self.max_target_length,
        )

        logger.info(
            "Training dataset: %d samples, Validation dataset: %d samples",
            len(train_dataset),
            len(val_dataset),
        )

        # Define training arguments
        checkpoint_dir = config.MODEL_CHECKPOINT_DIR
        training_args = Seq2SeqTrainingArguments(
            output_dir=checkpoint_dir,
            num_train_epochs=config.NUM_EPOCHS,
            per_device_train_batch_size=config.BATCH_SIZE,
            per_device_eval_batch_size=config.BATCH_SIZE,
            learning_rate=config.LEARNING_RATE,
            weight_decay=config.WEIGHT_DECAY,
            warmup_steps=config.WARMUP_STEPS,
            gradient_accumulation_steps=config.GRADIENT_ACCUMULATION_STEPS,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            load_best_model_at_end=True,
            predict_with_generate=True,
            generation_max_length=self.max_target_length,
            fp16=config.FP16 and torch.cuda.is_available(),
            logging_dir=os.path.join(checkpoint_dir, "logs"),
            logging_steps=50,
            report_to="none",
            seed=config.RANDOM_SEED,
        )

        # Data collator
        data_collator = DataCollatorForSeq2Seq(
            tokenizer=self.tokenizer,
            model=self.model,
            padding=True,
        )

        # Initialize trainer
        trainer = Seq2SeqTrainer(
            model=self.model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=val_dataset,
            tokenizer=self.tokenizer,
            data_collator=data_collator,
        )

        # Train
        logger.info("Starting fine-tuning...")
        trainer.train()

        # Save the best model
        final_checkpoint_path = os.path.join(checkpoint_dir, "best_model")
        trainer.save_model(final_checkpoint_path)
        self.tokenizer.save_pretrained(final_checkpoint_path)

        logger.info("Fine-tuning completed. Model saved to: %s", final_checkpoint_path)
        return final_checkpoint_path

    def summarize(self, text: str) -> str:
        """
        Generate an abstractive summary for a single document.

        Args:
            text: Raw input text string.

        Returns:
            Generated summary string.

        Raises:
            RuntimeError: If model is not loaded.
        """
        if self.model is None or self.tokenizer is None:
            raise RuntimeError(
                "Model not loaded. Call fine_tune() or load a checkpoint first."
            )

        if not text or not text.strip():
            logger.warning("Empty input text. Returning empty summary.")
            return ""

        # Add task prefix for raw mT5 models (not needed for fine-tuned XLSum)
        if "mt5" in self.model_name.lower() and "xlsum" not in self.model_name.lower():
            text = "summarize: " + text

        # Tokenize
        inputs = self.tokenizer(
            text,
            max_length=self.max_source_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).to(self.device)

        # Generate
        self.model.eval()
        with torch.no_grad():
            generated_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                max_length=self.max_target_length,
                num_beams=self.num_beams,
                early_stopping=True,
                no_repeat_ngram_size=3,
            )

        # Decode
        summary = self.tokenizer.decode(generated_ids[0], skip_special_tokens=True)

        logger.debug("Generated summary length: %d characters", len(summary))
        return summary

    def batch_summarize(self, texts: List[str]) -> List[str]:
        """
        Generate abstractive summaries for a batch of documents.

        Processes documents one at a time to manage memory usage,
        with progress tracking.

        Args:
            texts: List of raw input text strings.

        Returns:
            List of generated summary strings.

        Raises:
            RuntimeError: If model is not loaded.
        """
        if self.model is None or self.tokenizer is None:
            raise RuntimeError(
                "Model not loaded. Call fine_tune() or load a checkpoint first."
            )

        from tqdm import tqdm

        summaries = []
        for text in tqdm(texts, desc="Abstractive Summarization", unit="doc"):
            summary = self.summarize(text)
            summaries.append(summary)

        logger.info(
            "Batch abstractive summarization completed: %d documents",
            len(summaries),
        )
        return summaries

    def load_or_train(
        self,
        train_texts: Optional[List[str]] = None,
        train_summaries: Optional[List[str]] = None,
        val_texts: Optional[List[str]] = None,
        val_summaries: Optional[List[str]] = None,
    ) -> None:
        """
        Load a fine-tuned checkpoint if available, otherwise fine-tune.

        Args:
            train_texts: Training texts (required if no checkpoint exists).
            train_summaries: Training summaries (required if no checkpoint exists).
            val_texts: Validation texts (required if no checkpoint exists).
            val_summaries: Validation summaries (required if no checkpoint exists).
        """
        checkpoint_path = os.path.join(config.MODEL_CHECKPOINT_DIR, "best_model")

        if self._load_checkpoint(checkpoint_path):
            logger.info("Using existing fine-tuned checkpoint.")
            return

        logger.info("No checkpoint found. Starting fine-tuning...")

        if not all([train_texts, train_summaries, val_texts, val_summaries]):
            raise ValueError(
                "Training data must be provided when no checkpoint exists. "
                "Pass train_texts, train_summaries, val_texts, val_summaries."
            )

        self.fine_tune(train_texts, train_summaries, val_texts, val_summaries)


if __name__ == "__main__":
    """Test the AbstractiveSummarizer when run directly."""
    from src.utils import setup_logging

    setup_logging("DEBUG")

    # Only test initialization and basic structure — full test requires GPU
    summarizer = AbstractiveSummarizer()

    print("=" * 60)
    print("AbstractiveSummarizer Configuration:")
    print(f"  Model: {summarizer.model_name}")
    print(f"  Device: {summarizer.device}")
    print(f"  Max source length: {summarizer.max_source_length}")
    print(f"  Max target length: {summarizer.max_target_length}")
    print(f"  Num beams: {summarizer.num_beams}")
    print("=" * 60)

    # Test that model loading works
    try:
        summarizer._load_model()
        print("Model loaded successfully!")

        # Quick inference test
        sample_text = (
            "Penelitian ini bertujuan untuk menganalisis pengaruh media sosial "
            "terhadap prestasi akademik mahasiswa."
        )
        summary = summarizer.summarize(sample_text)
        print(f"\nSample input: {sample_text}")
        print(f"Generated summary: {summary}")
    except Exception as e:
        print(
            f"\nModel loading test skipped (expected in environments without model): {e}"
        )

    print("\nAbstractiveSummarizer module test completed.")
