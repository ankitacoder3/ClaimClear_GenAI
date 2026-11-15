"""ClaimClear document reader: PDF, JPG and PNG to text with source spans, hidden content kept apart, OCR for scans."""

from .extract import DocumentText, ExtractionError, extract_document
from .ocr import OcrSettings, ocr_available
from .reader import MAX_BYTES, MEDIA_TYPES, READER_VERSION, DocumentReader, sniff_media_type

__all__ = ["DocumentReader", "DocumentText", "ExtractionError", "MAX_BYTES", "MEDIA_TYPES", "OcrSettings",
           "READER_VERSION", "extract_document", "ocr_available", "sniff_media_type"]
