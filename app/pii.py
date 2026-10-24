from __future__ import annotations

import logging

import spacy
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

logger = logging.getLogger(__name__)

# Initialize AnalyzerEngine lazily to avoid blocking on spacy model download
_analyzer = None
_anonymizer = AnonymizerEngine()


def _get_analyzer() -> AnalyzerEngine:
    """Lazily initialize the Presidio analyzer engine."""
    global _analyzer
    if _analyzer is None:
        if not spacy.util.is_package("en_core_web_sm"):
            raise RuntimeError("PII model en_core_web_sm is missing. Run make setup-backend.")
        try:
            engine = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }).create_engine()
            _analyzer = AnalyzerEngine(nlp_engine=engine, supported_languages=["en"])
        except Exception as e:
            logger.error("Failed to initialize Presidio AnalyzerEngine: %s", e)
            raise
    return _analyzer

_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD",
    "IBAN_CODE",
    "IP_ADDRESS",
    "LOCATION",
    "NRP",
    "DATE_TIME",
    "MEDICAL_LICENSE",
    "URL",
]


def mask(text: str) -> tuple[str, list[dict]]:
    """Detect and mask PII entities in text using Microsoft Presidio.

    Args:
        text: Raw input string potentially containing PII.

    Returns:
        A tuple of (masked_text, found_entities) where found_entities is a
        list of dicts with keys 'entity_type', 'start', 'end', 'score'.
    """
    if not text.strip():
        return text, []

    analyzer = _get_analyzer()
    results = analyzer.analyze(text=text, entities=_ENTITIES, language="en")
    if not results:
        return text, []

    anonymized = _anonymizer.anonymize(text=text, analyzer_results=results)
    found = [
        {
            "entity_type": r.entity_type,
            "start": r.start,
            "end": r.end,
            "score": r.score,
        }
        for r in results
    ]
    logger.debug("PII masked: %d entities found", len(found))
    return anonymized.text, found
