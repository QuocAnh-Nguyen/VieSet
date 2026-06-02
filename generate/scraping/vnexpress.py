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

    async def _fetch_article_body(self, url: str) -> str:
        """Fetch full article body text from a VnExpress article page."""
        import asyncio
        try:
            resp = await self._fetch_with_retry(url, max_retries=2, backoff=1.0)
            from selectolax.parser import HTMLParser
            tree = HTMLParser(resp.text)
            # VnExpress article content containers
            for selector in [
                "article.fck_detail",
                "div.sidebar-1 > article",
                "section.container article",
                "div.width_common.content",
                "article.content_detail",
            ]:
                body_el = tree.css_first(selector)
                if body_el:
                    # Remove unwanted elements
                    for unwanted in body_el.css("div.related_news, div.box_tinlienquan, div.quangcao, iframe, script, style"):
                        unwanted.decompose()
                    text = body_el.text(strip=True)
                    if text and len(text) > 100:
                        return text[:2000]  # Cap at 2000 chars
            # Fallback: try to find the main article text by looking for largest text block
            candidates = []
            for p in tree.css("p.Normal, p"):
                t = p.text(strip=True)
                if t and len(t) > 60:
                    candidates.append(t)
            if candidates:
                return " ".join(candidates)[:2000]
            return ""
        except Exception as exc:
            logger.debug("vnexpress: failed to fetch article body for %s: %s", url, exc)
            return ""

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
                        content="",  # filled below for a subset
                        date=entry.get("published", ""),
                        tags=tags,
                    )
                )
                count += 1

        # Fetch full article bodies for a sample of articles (up to 10)
        sample_for_full = articles[: min(10, len(articles))]
        for i, art in enumerate(sample_for_full):
            if art.url:
                full_body = await self._fetch_article_body(art.url)
                if full_body:
                    articles[i].content = full_body
                    articles[i].snippet = full_body[:300]  # replace summary with real content lead

        logger.info(
            "vnexpress: fetched %d articles across %d feeds (%d with full body)",
            len(articles), len(self.feeds),
            sum(1 for a in articles[:10] if a.content),
        )
        return articles[: self.max_articles]
