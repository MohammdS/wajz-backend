"""AI provider abstraction.

The pipeline supports source-grounded Anthropic, Google Gemini, and Z.AI providers.
HeuristicProvider is the deterministic fallback (PRD 21.2: the app must still
work if AI processing fails or is unconfigured).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class ArticleAnalysis:
    category: str = "World"
    region: str = "World"
    language: str = "en"
    topic_tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    importance_score: float = 0.5
    short_summary: str = ""
    key_facts: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    unclear_points: list[str] = field(default_factory=list)
    is_opinion: bool = False


@dataclass
class StorySynthesis:
    headline: str = ""
    summary: str = ""
    what_happened: str = ""
    why_it_matters: str = ""
    key_facts: list[str] = field(default_factory=list)
    unclear_points: list[str] = field(default_factory=list)
    source_comparison: list[dict] = field(default_factory=list)  # [{source, framing}]


class AIProvider(ABC):
    name: str = "base"
    model_name: str = "none"

    @abstractmethod
    def analyze_article(self, title: str, text: str, source_name: str) -> ArticleAnalysis:
        """Classify and summarize a single article."""

    @abstractmethod
    def synthesize_story(self, articles: list[dict]) -> StorySynthesis:
        """Merge several articles about one event into a multi-source story.

        Each article dict: {source, title, summary, key_facts, why_it_matters,
        unclear_points, text}.
        """

    def translate_story(
        self,
        story: StorySynthesis,
        source_language: str,
        target_language: str,
    ) -> StorySynthesis | None:
        """Translate grounded story content. Providers may decline by returning None."""
        return None


@lru_cache
def get_provider() -> AIProvider:
    from app.config import get_settings
    from app.services.ai.heuristic_provider import HeuristicProvider

    settings = get_settings()
    provider = settings.ai_provider.lower()

    if provider == "heuristic":
        return HeuristicProvider()

    if provider == "anthropic" or (provider == "auto" and settings.anthropic_api_key):
        if not settings.anthropic_api_key:
            raise ValueError("AI_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        from app.services.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.ai_model)

    if provider == "gemini" or (provider == "auto" and settings.gemini_api_key):
        if not settings.gemini_api_key:
            raise ValueError("AI_PROVIDER=gemini requires GEMINI_API_KEY")
        from app.services.ai.gemini_provider import GeminiProvider

        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )

    if provider == "zai" or (provider == "auto" and settings.zai_api_key):
        if not settings.zai_api_key:
            raise ValueError("AI_PROVIDER=zai requires ZAI_API_KEY")
        from app.services.ai.zai_provider import ZAIProvider

        return ZAIProvider(
            api_key=settings.zai_api_key,
            model=settings.zai_model,
            base_url=settings.zai_base_url,
        )

    if provider != "auto":
        raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
    return HeuristicProvider()
