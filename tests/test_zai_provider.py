import json

import httpx
import pytest

from app.config import get_settings
from app.services.ai.base import get_provider
from app.services.ai.zai_provider import ZAIProvider


def test_zai_analyze_article_uses_chat_completions_json_mode():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        content = {
            "category": "Technology",
            "region": "World",
            "language": "en",
            "topic_tags": ["AI"],
            "entities": ["Z.AI"],
            "importance_score": 0.75,
            "short_summary": "A source-grounded summary.",
            "key_facts": ["One verified fact."],
            "why_it_matters": "It affects developers.",
            "unclear_points": [],
            "is_opinion": False,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    client = httpx.Client(
        base_url="https://api.z.ai/api/paas/v4",
        headers={"Authorization": "Bearer test-key"},
        transport=httpx.MockTransport(handler),
    )
    provider = ZAIProvider(api_key="ignored", model="glm-test", client=client)

    analysis = provider.analyze_article("Title", "Article body", "Source")

    assert captured["path"] == "/api/paas/v4/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "glm-test"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["thinking"] == {"type": "disabled"}
    assert analysis.category == "Technology"
    assert analysis.entities == ["Z.AI"]


def test_explicit_zai_provider_selection(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "zai")
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    get_settings.cache_clear()
    get_provider.cache_clear()

    try:
        provider = get_provider()
        assert isinstance(provider, ZAIProvider)
        assert provider.model_name == "glm-4.5-air"
    finally:
        get_provider.cache_clear()
        get_settings.cache_clear()


def test_explicit_zai_provider_requires_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "zai")
    monkeypatch.setenv("ZAI_API_KEY", "")
    get_settings.cache_clear()
    get_provider.cache_clear()

    try:
        with pytest.raises(ValueError, match="ZAI_API_KEY"):
            get_provider()
    finally:
        get_provider.cache_clear()
        get_settings.cache_clear()
