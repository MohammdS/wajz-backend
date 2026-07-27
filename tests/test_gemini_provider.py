import json
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services.ai.base import StorySynthesis, get_provider
from app.services.ai.gemini_provider import GeminiProvider


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(text=json.dumps(next(self.responses)))


def test_gemini_provider_uses_structured_outputs_for_analysis_and_translation():
    analysis = {
        "category": "Technology",
        "region": "World",
        "language": "en",
        "topic_tags": ["AI"],
        "entities": ["Wajz"],
        "importance_score": 0.8,
        "short_summary": "A grounded summary.",
        "key_facts": ["One fact"],
        "why_it_matters": "It matters.",
        "unclear_points": [],
        "is_opinion": False,
    }
    translation = {
        "headline": "عنوان",
        "summary": "ملخص",
        "what_happened": "ما حدث",
        "why_it_matters": "لماذا يهم",
        "key_facts": ["حقيقة"],
        "unclear_points": [],
        "source_comparison": [{"source": "BBC", "framing": "صياغة"}],
    }
    models = FakeModels([analysis, translation])
    provider = GeminiProvider(
        api_key="test-key",
        client=SimpleNamespace(models=models),
    )

    result = provider.analyze_article("Title", "Body", "BBC")
    translated = provider.translate_story(
        StorySynthesis(headline="Headline"),
        "en",
        "ar",
    )

    assert result.category == "Technology"
    assert translated.headline == "عنوان"
    assert len(models.requests) == 2
    assert all(
        request["config"]["response_mime_type"] == "application/json"
        and request["config"]["response_json_schema"]["type"] == "object"
        for request in models.requests
    )


def test_get_provider_selects_gemini(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        provider = get_provider()
        assert provider.name == "gemini"
        assert provider.model_name == "gemini-3.6-flash"
    finally:
        get_provider.cache_clear()
        get_settings.cache_clear()


def test_explicit_gemini_requires_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    get_provider.cache_clear()
    try:
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            get_provider()
    finally:
        get_provider.cache_clear()
        get_settings.cache_clear()
