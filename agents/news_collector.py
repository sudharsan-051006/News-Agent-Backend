import feedparser
from rss_sources import RSS_SOURCES
import time

feedparser.USER_AGENT = "AI-News-Agent/1.0 (+https://example.com)"


MAX_ARTICLES_PER_CATEGORY = 5


def fetch_tech_news():
    return fetch_from_rss("tech")


def fetch_geopolitics_news():
    return fetch_from_rss("geopolitics")


def fetch_sports_news():
    return fetch_from_rss("sports")


def fetch_movies_news():
    return fetch_from_rss("movies")


def fetch_from_rss(category):
    feed_urls = RSS_SOURCES.get(category)
    if not feed_urls:
        return []

    articles = []

    for feed_url in feed_urls:
        try:
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                continue

            for entry in feed.entries:
                if len(articles) >= MAX_ARTICLES_PER_CATEGORY:
                    break

                articles.append({
                    "category": category,
                    "title": entry.title,
                    "summary": entry.get("summary", ""),
                    "link": entry.link,
                    "source": feed_url
                })

            # polite delay (VERY important)
            time.sleep(1)

        except Exception as e:
            print(f"⚠️ RSS failed [{feed_url}]: {e}")
            continue

        if len(articles) >= MAX_ARTICLES_PER_CATEGORY:
            break

    return articles

def collect_news(categories):
    articles = []

    for category in categories:
        if category == "tech":
            articles += fetch_tech_news()

        elif category == "geopolitics":
            articles += fetch_geopolitics_news()

        elif category == "sports":
            articles += fetch_sports_news()

        elif category == "movies":
            articles += fetch_movies_news()

    return articles