"""Google Gemini provider using schema-constrained JSON responses."""

import json

from google import genai

from app.schemas import CATEGORIES, REGIONS
from app.services.ai.anthropic_provider import (
    _ANALYZE_SCHEMA,
    _ANALYZE_SYSTEM,
    _GROUNDING_RULES,
    _LANGUAGE_NAMES,
    _MAX_ARTICLE_CHARS,
    _SYNTH_SCHEMA,
    _SYNTH_SYSTEM,
)
from app.services.ai.base import AIProvider, ArticleAnalysis, StorySynthesis


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.6-flash",
        client=None,
    ):
        self.model_name = model
        self._client = client or genai.Client(api_key=api_key)

    def _request_json(self, system: str, prompt: str, schema: dict) -> dict:
        response = self._client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={
                "system_instruction": system,
                "max_output_tokens": 4096,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
        if not response.text:
            raise ValueError("Gemini returned an empty response")
        return json.loads(response.text)

    def analyze_article(self, title: str, text: str, source_name: str) -> ArticleAnalysis:
        data = self._request_json(
            _ANALYZE_SYSTEM,
            (
                f"Source: {source_name}\nTitle: {title}\n\n"
                f"Article text:\n{(text or '')[:_MAX_ARTICLE_CHARS]}"
            ),
            _ANALYZE_SCHEMA,
        )
        category = data.get("category", "World")
        region = data.get("region", "World")
        return ArticleAnalysis(
            category=category if category in CATEGORIES else "World",
            region=region if region in REGIONS else "World",
            language=(data.get("language") or "en")[:8],
            topic_tags=list(data.get("topic_tags") or [])[:8],
            entities=list(data.get("entities") or [])[:12],
            importance_score=max(
                0.0,
                min(1.0, float(data.get("importance_score", 0.5))),
            ),
            short_summary=str(data.get("short_summary") or ""),
            key_facts=list(data.get("key_facts") or [])[:6],
            why_it_matters=str(data.get("why_it_matters") or ""),
            unclear_points=list(data.get("unclear_points") or [])[:5],
            is_opinion=bool(data.get("is_opinion", False)),
        )

    def synthesize_story(self, articles: list[dict]) -> StorySynthesis:
        per_source_budget = max(1500, _MAX_ARTICLE_CHARS // max(1, len(articles)))
        parts = [
            (
                f"--- Source: {article['source']}\nTitle: {article['title']}\n"
                f"Summary: {article.get('summary') or ''}\n"
                f"Text: {(article.get('text') or '')[:per_source_budget]}"
            )
            for article in articles
        ]
        data = self._request_json(
            _SYNTH_SYSTEM,
            f"{len(articles)} articles covering the same event:\n\n" + "\n\n".join(parts),
            _SYNTH_SCHEMA,
        )
        return self._story_synthesis(data)

    def translate_story(
        self,
        story: StorySynthesis,
        source_language: str,
        target_language: str,
    ) -> StorySynthesis:
        target_name = _LANGUAGE_NAMES.get(target_language, target_language)
        prompt = (
            f"Translate this source-grounded news story from {source_language} to "
            f"{target_name}. Preserve names, numbers, uncertainty, and meaning exactly. "
            "Do not add facts or commentary. Return every field in the target language, "
            "except source names inside source_comparison, which must remain unchanged.\n\n"
            f"{json.dumps(story.__dict__, ensure_ascii=False)}"
        )
        return self._story_synthesis(self._request_json(_GROUNDING_RULES, prompt, _SYNTH_SCHEMA))

    @staticmethod
    def _story_synthesis(data: dict) -> StorySynthesis:
        return StorySynthesis(
            headline=str(data.get("headline") or ""),
            summary=str(data.get("summary") or ""),
            what_happened=str(data.get("what_happened") or ""),
            why_it_matters=str(data.get("why_it_matters") or ""),
            key_facts=list(data.get("key_facts") or [])[:8],
            unclear_points=list(data.get("unclear_points") or [])[:5],
            source_comparison=list(data.get("source_comparison") or []),
        )
