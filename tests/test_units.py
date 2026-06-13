from collections import Counter

from app.services.ai.heuristic_provider import (
    HeuristicProvider,
    classify_category,
    classify_region,
    extract_entities,
)
from app.services.cleaning import clean_text
from app.services.clustering import cosine_similarity, entity_overlap, tokenize
from app.services.safe_fetch import validate_public_url


def test_clean_text_strips_html_and_boilerplate():
    raw = (
        "<html><body><nav>Menu</nav><p>Real news content here today.</p>"
        "<p>Subscribe to our newsletter for updates!</p>"
        "<script>track();</script></body></html>"
    )
    cleaned = clean_text(raw)
    assert "Real news content" in cleaned
    assert "Subscribe" not in cleaned
    assert "track()" not in cleaned
    assert "Menu" not in cleaned


def test_tokenize_drops_stopwords():
    tokens = tokenize("The president said that the economy is growing")
    assert "the" not in tokens
    assert "president" in tokens
    assert "economy" in tokens


def test_cosine_similarity():
    a = Counter({"eu": 2, "ai": 3, "rules": 1})
    b = Counter({"eu": 1, "ai": 2, "regulation": 1})
    c = Counter({"football": 2, "cup": 1})
    assert cosine_similarity(a, b) > 0.7
    assert cosine_similarity(a, c) == 0.0
    assert cosine_similarity(Counter(), a) == 0.0


def test_entity_overlap():
    assert entity_overlap(["European Union", "OpenAI"], ["openai", "Google"]) == 0.5
    assert entity_overlap([], ["X"]) == 0.0


def test_classify_category():
    assert classify_category("New AI chip from semiconductor startup") == "Technology"
    assert classify_category("Central bank raises interest rate amid inflation") == "Economy"
    assert classify_category("The cup final match ended with a late goal") == "Sports"


def test_classify_region():
    assert classify_region("Talks in Gaza and Jerusalem continue") == "Israel / Palestine"
    assert classify_region("The European Union parliament in Brussels voted") == "Europe"


def test_extract_entities():
    entities = extract_entities(
        "The European Commission met with OpenAI. The European Commission proposed rules."
    )
    assert "European Commission" in entities


def test_heuristic_analysis_is_grounded():
    provider = HeuristicProvider()
    analysis = provider.analyze_article(
        "Markets rise after rate decision",
        "Stocks rose 2 percent on Wednesday. The central bank held rates at 5 percent. "
        "Analysts expect one cut this year.",
        "BBC News",
    )
    assert analysis.category == "Economy"
    assert analysis.short_summary.startswith("Stocks rose")
    # Heuristic mode must never invent interpretation
    assert analysis.why_it_matters == ""
    assert all("percent" in fact or any(ch.isdigit() for ch in fact) for fact in analysis.key_facts)


def test_safe_fetch_blocks_internal_urls():
    import pytest

    for url in (
        "http://localhost/article",
        "http://127.0.0.1/article",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ftp://example.com/article",
    ):
        with pytest.raises(ValueError):
            validate_public_url(url)
