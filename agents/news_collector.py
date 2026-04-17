import feedparser
import time
from collections import defaultdict

# -------------------------------
# ⚙️ Config
# -------------------------------
feedparser.USER_AGENT = "AI-News-Agent/1.0 (+https://example.com)"

MAX_ARTICLES_PER_CATEGORY = 5
RECENCY_WEIGHT = 0.5
POPULARITY_WEIGHT = 0.5


# -------------------------------
# 🕒 Helpers
# -------------------------------
def _entry_timestamp(entry) -> float:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        return time.mktime(published)
    return 0.0


def _entry_popularity(entry) -> int:
    popularity_fields = [
        entry.get("slash_comments"),
        entry.get("comment_count"),
        entry.get("comments"),
        entry.get("views"),
    ]
    for value in popularity_fields:
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return 0


# -------------------------------
# 🌐 MAIN FUNCTION
# -------------------------------
def fetch_from_rss_sources(sources):
    if not sources:
        return []

    articles = []

    # -------------------------------
    # 📡 FETCH RSS
    # -------------------------------
    for source in sources:
        feed_url = source["rss_url"]
        category = source["category"]

        try:
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                continue

            for entry in feed.entries:
                articles.append({
                    "category": category,
                    "title": entry.title,
                    "summary": entry.get("summary", ""),
                    "link": entry.link,
                    "source": feed_url,
                    "published_ts": _entry_timestamp(entry),
                    "popularity": _entry_popularity(entry),
                })

            time.sleep(1)

        except Exception as e:
            print(f"⚠️ RSS failed [{feed_url}]: {e}")
            continue

    # -------------------------------
    # 🔁 DEDUPLICATION
    # -------------------------------
    deduped = {}

    for article in articles:
        key = article.get("link") or f"{article['source']}::{article['title']}"
        existing = deduped.get(key)

        if not existing:
            deduped[key] = article
            continue

        if (article["published_ts"], article["popularity"]) > (
            existing["published_ts"], existing["popularity"]
        ):
            deduped[key] = article

    deduped_values = list(deduped.values())

    if not deduped_values:
        return []

    # -------------------------------
    # 📊 SCORING
    # -------------------------------
    max_ts = max((a["published_ts"] for a in deduped_values), default=0.0)
    max_pop = max((a["popularity"] for a in deduped_values), default=0)

    def _score(article):
        recency_score = (article["published_ts"] / max_ts) if max_ts else 0.0
        popularity_score = (article["popularity"] / max_pop) if max_pop else 0.0
        return (RECENCY_WEIGHT * recency_score) + (POPULARITY_WEIGHT * popularity_score)

    ranked = sorted(
        deduped_values,
        key=lambda a: (_score(a), a["published_ts"], a["popularity"]),
        reverse=True,
    )

    # -------------------------------
    # ✅ BALANCED SELECTION
    # -------------------------------
    category_map = defaultdict(list)

    for article in ranked:
        category_map[article["category"]].append(article)

    final = []

    for category, items in category_map.items():
        source_map = defaultdict(list)

        # group by source
        for item in items:
            source_map[item["source"]].append(item)

        # round-robin selection
        selected = []
        sources = list(source_map.keys())
        i = 0

        while len(selected) < MAX_ARTICLES_PER_CATEGORY:
            if not sources:
                break

            source = sources[i % len(sources)]
            source_items = source_map[source]

            if source_items:
                selected.append(source_items.pop(0))

            # remove empty sources
            if not source_items:
                sources.remove(source)
                i -= 1

            i += 1

        final.extend(selected)

    return final
