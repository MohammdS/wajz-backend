"""Anthropic-backed analysis. Summaries are strictly source-grounded:
the prompts forbid speculation and external facts (PRD 12.4 / 29.2).
"""

import json
import logging

import anthropic

from app.services.ai.base import AIProvider, ArticleAnalysis, StorySynthesis
from app.schemas import CATEGORIES, REGIONS

logger = logging.getLogger(__name__)

_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "region": {"type": "string", "enum": REGIONS},
        "language": {"type": "string"},
        "topic_tags": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "importance_score": {"type": "number"},
        "short_summary": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "why_it_matters": {"type": "string"},
        "unclear_points": {"type": "array", "items": {"type": "string"}},
        "is_opinion": {"type": "boolean"},
    },
    "required": [
        "category", "region", "language", "topic_tags", "entities",
        "importance_score", "short_summary", "key_facts", "why_it_matters",
        "unclear_points", "is_opinion",
    ],
    "additionalProperties": False,
}

_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "what_happened": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "unclear_points": {"type": "array", "items": {"type": "string"}},
        "source_comparison": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "framing": {"type": "string"},
                },
                "required": ["source", "framing"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "headline", "summary", "what_happened", "why_it_matters",
        "key_facts", "unclear_points", "source_comparison",
    ],
    "additionalProperties": False,
}

_GROUNDING_RULES = (
    "Rules: Use only the provided article content. Do not add external facts. "
    "Do not speculate. If something is uncertain, list it under unclear_points. "
    "Write in a calm, clear, neutral tone - no clickbait, no dramatic language. "
    "Keep the summary to 2-3 short sentences."
)

_ANALYZE_SYSTEM = (
    "You are the background news-analysis engine for Wajz, a calm, trust-first "
    "news briefing app. You classify and summarize a single news article. "
    + _GROUNDING_RULES
)

_SYNTH_SYSTEM = (
    "You are the background news-analysis engine for Wajz, a calm, trust-first "
    "news briefing app. You merge several articles covering the SAME event into "
    "one neutral multi-source story. For source_comparison, describe in one short "
    "sentence how each source frames the story. " + _GROUNDING_RULES
)

_MAX_ARTICLE_CHARS = 12000

_LANGUAGE_NAMES = {
    "en": "English",
    "ar": "Arabic",
    "he": "Hebrew",
}


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-4-8"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_name = model

    def _request_json(self, system: str, prompt: str, schema: dict) -> dict:
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)

    def analyze_article(self, title: str, text: str, source_name: str) -> ArticleAnalysis:
        prompt = (
            f"Source: {source_name}\nTitle: {title}\n\n"
            f"Article text:\n{(text or '')[:_MAX_ARTICLE_CHARS]}"
        )
        data = self._request_json(_ANALYZE_SYSTEM, prompt, _ANALYZE_SCHEMA)
        return ArticleAnalysis(
            category=data["category"],
            region=data["region"],
            language=(data["language"] or "en")[:8],
            topic_tags=data["topic_tags"][:8],
            entities=data["entities"][:12],
            importance_score=max(0.0, min(1.0, float(data["importance_score"]))),
            short_summary=data["short_summary"],
            key_facts=data["key_facts"][:6],
            why_it_matters=data["why_it_matters"],
            unclear_points=data["unclear_points"][:5],
            is_opinion=bool(data["is_opinion"]),
        )

    def synthesize_story(self, articles: list[dict]) -> StorySynthesis:
        per_source_budget = max(1500, _MAX_ARTICLE_CHARS // max(1, len(articles)))
        parts = []
        for a in articles:
            parts.append(
                f"--- Source: {a['source']}\nTitle: {a['title']}\n"
                f"Summary: {a.get('summary') or ''}\n"
                f"Text: {(a.get('text') or '')[:per_source_budget]}"
            )
        prompt = (
            f"{len(articles)} articles covering the same event:\n\n" + "\n\n".join(parts)
        )
        data = self._request_json(_SYNTH_SYSTEM, prompt, _SYNTH_SCHEMA)
        return StorySynthesis(
            headline=data["headline"],
            summary=data["summary"],
            what_happened=data["what_happened"],
            why_it_matters=data["why_it_matters"],
            key_facts=data["key_facts"][:8],
            unclear_points=data["unclear_points"][:5],
            source_comparison=data["source_comparison"],
        )

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
        data = self._request_json(_GROUNDING_RULES, prompt, _SYNTH_SCHEMA)
        return StorySynthesis(
            headline=data["headline"],
            summary=data["summary"],
            what_happened=data["what_happened"],
            why_it_matters=data["why_it_matters"],
            key_facts=data["key_facts"][:8],
            unclear_points=data["unclear_points"][:5],
            source_comparison=data["source_comparison"],
        )
