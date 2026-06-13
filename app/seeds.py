"""Seed data.

Usage:
    python -m app.seeds sources   # seed trusted RSS sources
    python -m app.seeds demo      # seed offline demo articles + run the pipeline
    python -m app.seeds all
"""

import sys
from datetime import timedelta

from app.database import Base, SessionLocal, engine
from app.models import Article, Source, Story, StoryArticle, utcnow
from app.services.ai.base import StorySynthesis
from app.services.cleaning import clean_text
from app.services.pipeline import process_pending_articles
from app.services.translations import upsert_translation

TRUSTED_SOURCES = [
    {
        "name": "BBC News",
        "website_url": "https://www.bbc.com/news",
        "rss_url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "country": "United Kingdom",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "NPR",
        "website_url": "https://www.npr.org",
        "rss_url": "https://feeds.npr.org/1001/rss.xml",
        "country": "United States",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "The Guardian",
        "website_url": "https://www.theguardian.com",
        "rss_url": "https://www.theguardian.com/world/rss",
        "country": "United Kingdom",
        "language": "en",
        "reliability_level": "high",
    },
    {
        "name": "Al Jazeera English",
        "website_url": "https://www.aljazeera.com",
        "rss_url": "https://www.aljazeera.com/xml/rss/all.xml",
        "country": "Qatar",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "The Verge",
        "website_url": "https://www.theverge.com",
        "rss_url": "https://www.theverge.com/rss/index.xml",
        "country": "United States",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "Ars Technica",
        "website_url": "https://arstechnica.com",
        "rss_url": "https://feeds.arstechnica.com/arstechnica/index",
        "country": "United States",
        "language": "en",
        "reliability_level": "medium",
    },
    {
        "name": "The Times of Israel",
        "website_url": "https://www.timesofisrael.com",
        "rss_url": "https://www.timesofisrael.com/feed/",
        "country": "Israel",
        "language": "en",
        "reliability_level": "medium",
    },
]

# Fictional demo articles so the full flow works offline. Three of them cover
# the same event from different sources to exercise clustering.
_NOW = utcnow()
DEMO_ARTICLES = [
    {
        "source": "BBC News",
        "title": "EU proposes stricter AI model rules",
        "url": "https://demo.wajz.app/bbc/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=3),
        "text": (
            "The European Commission proposed new rules on Tuesday that would require large "
            "AI companies to disclose more details about model safety and training data. "
            "The proposal covers models above a defined compute threshold and would take "
            "effect in 2027. Regulators said the measure is needed for accountability. "
            "Several technology companies warned the rules could slow innovation in Europe. "
            "The proposal now moves to the European Parliament for debate."
        ),
    },
    {
        "source": "The Verge",
        "title": "Europe wants AI giants to open up about training data",
        "url": "https://demo.wajz.app/verge/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=2),
        "text": (
            "The European Commission unveiled a proposal requiring major AI developers to "
            "publish summaries of training data and safety testing results. The draft rules "
            "target models above a compute threshold and include fines of up to 4 percent of "
            "global revenue. Industry groups criticized the timeline as unrealistic, while "
            "consumer organizations welcomed the transparency requirements."
        ),
    },
    {
        "source": "The Guardian",
        "title": "EU unveils transparency rules for powerful AI systems",
        "url": "https://demo.wajz.app/guardian/eu-ai-rules",
        "published_at": _NOW - timedelta(hours=1),
        "text": (
            "European Union officials presented draft legislation that would force developers "
            "of the most powerful AI systems to disclose safety evaluations and training data "
            "sources. The European Commission said the rules build on the AI Act and respond "
            "to rapid advances in general-purpose models. A vote in the European Parliament "
            "is expected next year. Civil society groups called the proposal a step toward "
            "accountability, while several companies said compliance costs would be significant."
        ),
    },
    {
        "source": "NPR",
        "title": "Global markets steady as central banks hold interest rates",
        "url": "https://demo.wajz.app/npr/markets-rates",
        "published_at": _NOW - timedelta(hours=5),
        "text": (
            "Stock markets were broadly stable on Wednesday after central banks in the United "
            "States and Europe kept interest rates unchanged. The Federal Reserve said inflation "
            "continues to ease toward its 2 percent target. Analysts expect one rate cut later "
            "this year. Bond yields fell slightly following the announcements."
        ),
    },
    {
        "source": "Ars Technica",
        "title": "Astronomers detect water vapor on distant exoplanet",
        "url": "https://demo.wajz.app/ars/exoplanet-water",
        "published_at": _NOW - timedelta(hours=8),
        "text": (
            "Scientists using the James Webb Space Telescope reported detecting water vapor in "
            "the atmosphere of an exoplanet 120 light-years away. The planet, located in its "
            "star's habitable zone, is roughly twice the size of Earth. Researchers cautioned "
            "that water vapor alone does not indicate life. The findings were published in the "
            "journal Nature Astronomy."
        ),
    },
    {
        "source": "Al Jazeera English",
        "title": "Regional leaders meet for economic cooperation summit",
        "url": "https://demo.wajz.app/aljazeera/regional-summit",
        "published_at": _NOW - timedelta(hours=6),
        "text": (
            "Leaders from across the Middle East gathered in Amman on Thursday for a two-day "
            "summit focused on regional trade and water security. Delegates discussed a proposed "
            "rail corridor linking Gulf ports to the Mediterranean. Officials said agreements on "
            "cross-border energy projects are expected to be signed on Friday. Jordan's prime "
            "minister called the talks constructive."
        ),
    },
    {
        "source": "The Times of Israel",
        "title": "Tech sector hiring rebounds in first quarter, report finds",
        "url": "https://demo.wajz.app/toi/tech-hiring",
        "published_at": _NOW - timedelta(hours=10),
        "text": (
            "Hiring in the technology sector grew 8 percent in the first quarter compared with "
            "the previous year, according to a report released Sunday by the Innovation "
            "Authority. The report counted 12,400 new positions, concentrated in cybersecurity "
            "and AI companies. Startup funding rose to 2.1 billion dollars in the quarter. "
            "Economists said the rebound signals renewed investor confidence."
        ),
    },
]

DEMO_ARABIC_TRANSLATIONS = {
    "eu-ai-rules": StorySynthesis(
        headline="الاتحاد الأوروبي يقترح قواعد شفافية أشد لأنظمة الذكاء الاصطناعي",
        summary=(
            "اقترحت المفوضية الأوروبية إلزام مطوري نماذج الذكاء الاصطناعي الكبرى "
            "بالكشف عن اختبارات السلامة ومصادر بيانات التدريب. وما زال المقترح بحاجة "
            "إلى نقاش وتصويت في البرلمان الأوروبي."
        ),
        what_happened=(
            "كشفت المفوضية الأوروبية عن مسودة قواعد تستهدف أقوى نماذج الذكاء "
            "الاصطناعي وتفرض متطلبات إضافية للشفافية والسلامة."
        ),
        why_it_matters=(
            "قد تحدد القواعد مستوى المساءلة المطلوب من شركات الذكاء الاصطناعي "
            "الكبرى العاملة في أوروبا."
        ),
        key_facts=[
            "تشمل المسودة الإفصاح عن تقييمات السلامة وملخصات بيانات التدريب.",
            "تستهدف القواعد النماذج التي تتجاوز حداً معيناً من القدرة الحاسوبية.",
            "انتقدت شركات تقنية تكاليف الامتثال والجدول الزمني المقترح.",
        ],
        unclear_points=[
            "قد تتغير الصياغة النهائية خلال مناقشات البرلمان الأوروبي.",
        ],
        source_comparison=[
            {"source": "BBC News", "framing": "ركزت على المساءلة ومخاوف تباطؤ الابتكار."},
            {"source": "The Verge", "framing": "ركزت على بيانات التدريب والغرامات المحتملة."},
            {"source": "The Guardian", "framing": "ركزت على تقييمات السلامة وتكاليف الامتثال."},
        ],
    ),
    "markets-rates": StorySynthesis(
        headline="استقرار الأسواق مع إبقاء البنوك المركزية أسعار الفائدة دون تغيير",
        summary=(
            "استقرت أسواق الأسهم عموماً بعد أن أبقت البنوك المركزية في الولايات "
            "المتحدة وأوروبا أسعار الفائدة دون تغيير."
        ),
        what_happened=(
            "أبقى الاحتياطي الفيدرالي وبنوك مركزية أوروبية أسعار الفائدة ثابتة، "
            "بينما انخفضت عوائد السندات بشكل طفيف."
        ),
        why_it_matters="تؤثر قرارات الفائدة في الاقتراض والاستثمار والأسواق المالية.",
        key_facts=[
            "قال الاحتياطي الفيدرالي إن التضخم يواصل التراجع نحو هدف 2 بالمئة.",
            "يتوقع محللون خفضاً واحداً للفائدة في وقت لاحق من العام.",
        ],
    ),
    "exoplanet-water": StorySynthesis(
        headline="رصد بخار ماء في الغلاف الجوي لكوكب بعيد",
        summary=(
            "أعلن علماء يستخدمون تلسكوب جيمس ويب رصد بخار ماء في غلاف كوكب "
            "خارج المجموعة الشمسية يبعد 120 سنة ضوئية."
        ),
        what_happened=(
            "رصد الباحثون بخار ماء على كوكب يقع ضمن المنطقة الصالحة للحياة حول نجمه."
        ),
        why_it_matters="تساعد الملاحظة العلماء على دراسة أغلفة الكواكب البعيدة.",
        key_facts=[
            "يبعد الكوكب نحو 120 سنة ضوئية.",
            "يبلغ حجمه نحو ضعفي حجم الأرض.",
            "حذر الباحثون من أن وجود بخار الماء لا يعني وجود حياة.",
        ],
    ),
    "regional-summit": StorySynthesis(
        headline="قادة إقليميون يبحثون التعاون الاقتصادي وأمن المياه",
        summary=(
            "اجتمع قادة من الشرق الأوسط في عمّان لقمة تستمر يومين وتركز على "
            "التجارة الإقليمية وأمن المياه."
        ),
        what_happened=(
            "ناقش المشاركون ممراً للسكك الحديدية ومشروعات طاقة عابرة للحدود."
        ),
        why_it_matters="قد تعزز الاتفاقات المحتملة الترابط الاقتصادي بين دول المنطقة.",
        key_facts=[
            "تستمر القمة يومين في عمّان.",
            "يتوقع توقيع اتفاقات لمشروعات طاقة عابرة للحدود.",
        ],
    ),
    "tech-hiring": StorySynthesis(
        headline="تقرير: تعافي التوظيف في قطاع التكنولوجيا خلال الربع الأول",
        summary=(
            "أظهر تقرير نمو التوظيف في قطاع التكنولوجيا 8 بالمئة خلال الربع الأول "
            "مقارنة بالعام السابق، مع تركّز الوظائف في الأمن السيبراني والذكاء الاصطناعي."
        ),
        what_happened=(
            "سجل التقرير 12,400 وظيفة جديدة وارتفاع تمويل الشركات الناشئة إلى "
            "2.1 مليار دولار."
        ),
        why_it_matters="قد يشير التعافي إلى عودة ثقة المستثمرين في القطاع.",
        key_facts=[
            "نما التوظيف 8 بالمئة مقارنة بالعام السابق.",
            "سجل التقرير 12,400 وظيفة جديدة.",
            "بلغ تمويل الشركات الناشئة 2.1 مليار دولار.",
        ],
    ),
}


def seed_sources(db) -> None:
    for spec in TRUSTED_SOURCES:
        if not db.query(Source).filter(Source.name == spec["name"]).first():
            db.add(Source(**spec))
    db.commit()
    print(f"Sources seeded ({db.query(Source).count()} total).")


def seed_demo(db) -> None:
    seed_sources(db)
    sources = {s.name: s for s in db.query(Source).all()}
    added = 0
    for spec in DEMO_ARTICLES:
        if db.query(Article).filter(Article.url == spec["url"]).first():
            continue
        db.add(
            Article(
                source_id=sources[spec["source"]].id,
                title=spec["title"],
                url=spec["url"],
                published_at=spec["published_at"],
                language="en",
                raw_text=spec["text"],
                cleaned_text=clean_text(spec["text"]),
                processing_status="pending",
            )
        )
        added += 1
    db.commit()
    print(f"Demo articles added: {added}")
    result = process_pending_articles(db)
    # Demo fixtures are reviewed content. Live pipeline output remains
    # pending_review until an editor explicitly publishes it.
    for story in db.query(Story).all():
        story.status = "published"
        story.published_at = utcnow()
    db.commit()
    seed_demo_translations(db)
    print(f"Pipeline: {result}")


def seed_demo_translations(db) -> None:
    articles = db.query(Article).filter(Article.url.like("https://demo.wajz.app/%")).all()
    translated_story_ids: set[str] = set()
    for article in articles:
        key = next(
            (candidate for candidate in DEMO_ARABIC_TRANSLATIONS if candidate in article.url),
            None,
        )
        if key is None:
            continue
        link = (
            db.query(StoryArticle)
            .filter(StoryArticle.article_id == article.id)
            .first()
        )
        if link is None:
            continue
        story = link.story
        if story.id in translated_story_ids:
            continue
        upsert_translation(
            db,
            story,
            "ar",
            DEMO_ARABIC_TRANSLATIONS[key],
            "reviewed-demo",
        )
        translated_story_ids.add(story.id)
    db.commit()


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if command in ("sources", "all"):
            seed_sources(db)
        if command in ("demo", "all"):
            seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
