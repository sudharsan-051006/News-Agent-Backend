import time



RSS_SOURCES = {
    "tech": [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://news.ycombinator.com/rss",
        "https://dev.to/feed"
    ],
    "sports": [
        "https://www.espn.com/espn/rss/news",
        "https://www.espncricinfo.com/team/india-6/rss.xml"
    ],
    "movies": [
        "https://www.hollywoodreporter.com/feed/",
        "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms"
        
    ],
    "geopolitics": [
        "https://feeds.reuters.com/Reuters/worldNews",
        "https://feeds.bbci.co.uk/news/world/rss.xml"
    ],
    "local" : [
        "https://www.thehindu.com/news/feeder/default.rss",
        "https://ddnews.gov.in/rss-feeds"
    ]
}

print(RSS_SOURCES)
