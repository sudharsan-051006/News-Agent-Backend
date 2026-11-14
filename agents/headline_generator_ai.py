import feedparser
from rss_sources import RSS_SOURCES

def collect_news(categories, max_articles=5):
    """
    categories: ["tech", "sports"]
    returns: list of articles
    """

    articles = []

    for category in categories:
        feeds = RSS_SOURCES.get(category, [])

        for feed_url in feeds:
            feed = feedparser.parse(feed_url)

            for entry in feed.entries[:max_articles]:
                articles.append({
                    "category": category,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "link": entry.get("link", "")
                })

    return articles
