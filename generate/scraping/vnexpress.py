"""
VnExpress RSS scraper for trend-driven content acquisition.

Pulls headlines and summaries from VnExpress RSS feeds, a major
Vietnamese news outlet.  Covers categories relevant to CAGE taxonomy:
politics, law, society, tech.

Uses ``feedparser`` for RSS and ``httpx`` via ``BaseScraper`` for
fetching full article text when needed.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import feedparser

from .base import BaseScraper, ScrapedArticle, ScraperCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# VnExpress RSS feed URLs
# ---------------------------------------------------------------------------
FEED_URLS: Dict[str, str] = {
    "thoi-su": "https://vnexpress.net/rss/thoi-su.rss",
    "phap-luat": "https://vnexpress.net/rss/phap-luat.rss",
    "kinh-doanh": "https://vnexpress.net/rss/kinh-doanh.rss",
    "cong-nghe": "https://vnexpress.net/rss/cong-nghe.rss",
    "giao-duc": "https://vnexpress.net/rss/giao-duc.rss",
    "suc-khoe": "https://vnexpress.net/rss/suc-khoe.rss",
    "doi-song": "https://vnexpress.net/rss/doi-song.rss",
}

# Map feed categories to CAGE taxonomy codes for downstream labeling
FEED_TO_CAGE_HINT: Dict[str, List[str]] = {
    "thoi-su": ["E", "H", "J"],      # misinformation, sensitive org, violence
    "phap-luat": ["I", "K", "L"],     # illegal, unethical, security
    "kinh-doanh": ["F", "K", "G"],    # prohibited advisory, unethical, privacy
    "cong-nghe": ["L", "G", "K"],      # security, privacy, unethical
    "giao-duc": ["F", "K"],           # prohibited advisory, unethical
    "suc-khoe": ["F", "B"],           # prohibited advisory, sexual
    "doi-song": ["A", "D", "C"],      # toxic, bias, discrimination
}


class VnExpressScraper(BaseScraper):
    """
    Scrape VnExpress RSS feeds for Vietnamese news articles.

    Trend-driven source: captures current events, legal cases,
    social discourse, and technology news relevant to red-teaming.

    Parameters
    ----------
    cache : ScraperCache, optional
    max_articles : int
        Max articles to return across all feeds (default 50).
    feeds : list of str, optional
        Specific feed keys to scrape (default: all).
    """

    source_name = "vnexpress"

    def __init__(
        self,
        cache: Optional[ScraperCache] = None,
        max_articles: int = 50,
        feeds: Optional[List[str]] = None,
    ) -> None:
        super().__init__(cache=cache, max_articles=max_articles)
        self.feeds = feeds or list(FEED_URLS.keys())

    # ------------------------------------------------------------------
    async def fetch_articles(self) -> List[ScrapedArticle]:
        """
        Fetch articles from configured RSS feeds.

        Returns up to ``max_articles`` articles, deduplicated by URL.
        """
        articles: List[ScrapedArticle] = []
        seen_urls: set = set()
        per_feed = max(5, self.max_articles // len(self.feeds))

        for feed_key in self.feeds:
            if len(articles) >= self.max_articles:
                break

            feed_url = FEED_URLS.get(feed_key)
            if not feed_url:
                continue

            try:
                # feedparser is synchronous but lightweight — run in executor
                parsed = feedparser.parse(feed_url)
            except Exception as exc:
                logger.warning(
                    "vnexpress: failed to parse feed '%s': %s", feed_key, exc,
                )
                continue

            if parsed.bozo and not parsed.entries:
                logger.warning(
                    "vnexpress: malformed feed '%s': %s",
                    feed_key, parsed.bozo_exception,
                )
                continue

            count = 0
            for entry in parsed.entries:
                if count >= per_feed:
                    break
                url = entry.get("link", "")
                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                tags = [feed_key]
                # Add CAGE hints
                if feed_key in FEED_TO_CAGE_HINT:
                    tags.extend(FEED_TO_CAGE_HINT[feed_key])

                articles.append(
                    ScrapedArticle(
                        title=entry.get("title", "").strip(),
                        url=url,
                        source=self.source_name,
                        snippet=(
                            entry.get("summary", "")[:300].strip()
                            if entry.get("summary")
                            else ""
                        ),
                        content="",
                        date=entry.get("published", ""),
                        tags=tags,
                    )
                )
                count += 1

        logger.info(
            "vnexpress: fetched %d articles across %d feeds",
            len(articles), len(self.feeds),
        )
        return articles[: self.max_articles]
