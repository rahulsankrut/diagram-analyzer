"""Ingestion package — format normalization, GCS upload, Firestore persistence."""

from src.ingestion.firestore_adapter import FirestoreAdapter
from src.ingestion.gcs_adapter import GCSAdapter
from src.ingestion.normalizer import FormatNormalizer, UnsupportedFormatError

__all__ = [
    "FirestoreAdapter",
    "GCSAdapter",
    "FormatNormalizer",
    "UnsupportedFormatError",
]
