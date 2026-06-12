def test_categories(client):
    data = client.get("/categories").json()
    assert "Technology" in data["categories"]
    assert "Middle East" in data["regions"]


def test_sources_empty_then_seeded(client, demo_data):
    sources = client.get("/sources").json()
    names = {s["name"] for s in sources}
    assert "BBC News" in names
    # rss_url is internal-only and must not leak through the public API
    assert all("rss_url" not in s for s in sources)


def test_list_stories(client, demo_data):
    data = client.get("/stories").json()
    assert data["total"] >= 4
    item = data["items"][0]
    assert item["headline"]
    assert item["confidence_display"]
    assert isinstance(item["sources"], list)


def test_list_stories_category_filter(client, demo_data):
    data = client.get("/stories", params={"category": "Technology"}).json()
    assert data["total"] >= 1
    assert all(item["category"] == "Technology" for item in data["items"])


def test_story_detail_includes_sources(client, demo_data):
    stories = client.get("/stories").json()["items"]
    detail = client.get(f"/stories/{stories[0]['id']}").json()
    assert detail["headline"]
    assert len(detail["sources"]) >= 1
    for source in detail["sources"]:
        assert source["url"].startswith("http")


def test_story_detail_404(client):
    assert client.get("/stories/does-not-exist").status_code == 404
