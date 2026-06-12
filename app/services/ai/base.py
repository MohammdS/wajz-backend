"""AI provider abstraction.

The pipeline talks to an AIProvider. AnthropicProvider produces source-grounded
LLM analysis; HeuristicProvider is the deterministic fallback (PRD 21.2: the app
must still work if AI processing fails or is unconfigured).
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


@lru_cache
def get_provider() -> AIProvider:
    from app.config import get_settings
    from app.services.ai.heuristic_provider import HeuristicProvider

    settings = get_settings()
    if settings.anthropic_api_key:
        from app.services.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.ai_model)
    return HeuristicProvider()
