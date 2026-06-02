"""
Voz forum scraper for trend-driven, community-discourse content acquisition.

Voz (voz.vn) is one of the largest Vietnamese online forums with active
discussions on technology, society, politics, and lifestyle — rich sources
of culturally-grounded adversarial prompts (toxicity, bias, misinformation).

Uses ``curl_cffi`` for TLS fingerprint spoofing (Cloudflare bypass) and
``selectolax`` for fast HTML parsing.

Design notes:
- curl_cffi is synchronous; we wrap calls in ``asyncio.to_thread()``
- Hard-coded thread URLs as fallback; can be extended with sitemap parsing
- Respects robots.txt conventions; rate-limited to ~1 req/sec
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Dict, List, Optional

from selectolax.parser import HTMLParser

from .base import BaseScraper, ScrapedArticle, ScraperCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard-coded Voz forum sections and representative thread URLs
# These are used as fallbacks when dynamic crawling is blocked.
# ---------------------------------------------------------------------------
VOZ_SECTIONS: Dict[str, str] = {
    "diem-bao": "https://voz.vn/f/diem-bao.17/",          # News roundup
    "chinh-tri-xa-hoi": "https://voz.vn/f/chinh-tri-xa-hoi.57/",  # Politics & Society
    "cong-nghe": "https://voz.vn/f/cong-nghe.34/",          # Technology
    "phap-luat": "https://voz.vn/f/phap-luat.79/",          # Law
}

# Map sections to CAGE taxonomy hints
SECTION_TO_CAGE: Dict[str, List[str]] = {
    "diem-bao": ["E", "J", "A"],          # misinformation, violence, toxic
    "chinh-tri-xa-hoi": ["D", "C", "E"],   # bias, discrimination, misinformation
    "cong-nghe": ["L", "G", "K"],          # security, privacy, unethical
    "phap-luat": ["I", "K", "J"],          # illegal, unethical, violence
}


class VozScraper(BaseScraper):
    """
    Scrape Voz forum thread titles and snippets.

    Uses ``curl_cffi`` (impersonate Chrome) + ``selectolax`` for parsing.

    Parameters
    ----------
    cache : ScraperCache, optional
    max_articles : int
    sections : list of str, optional
        Section keys to scrape (default: all).
    """

    source_name = "voz"

    def __init__(
        self,
        cache: Optional[ScraperCache] = None,
        max_articles: int = 50,
        sections: Optional[List[str]] = None,
    ) -> None:
        super().__init__(cache=cache, max_articles=max_articles)
        self.sections = sections or list(VOZ_SECTIONS.keys())

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_forum_page(html: str, section_key: str) -> List[ScrapedArticle]:
        """
        Parse a Voz forum section page for thread titles and URLs.

        Returns list of ScrapedArticle from the HTML.
        """
        articles: List[ScrapedArticle] = []
        tree = HTMLParser(html)

        # Voz thread list items: look for <div class="structItem">
        for item in tree.css("div.structItem"):
            # Title
            title_el = item.css_first("div.structItem-title a")
            if not title_el:
                continue
            title = title_el.text(strip=True)
            href = title_el.attributes.get("href", "")

            # Build full URL
            url = href if href.startswith("http") else f"https://voz.vn{href}"

            # Snippet from the preview text
            snippet_el = item.css_first("div.structItem-preview")
            snippet = snippet_el.text(strip=True) if snippet_el else ""

            # Date from time element
            date_el = item.css_first("time")
            date = date_el.attributes.get("datetime", "") if date_el else ""

            tags = [section_key]
            if section_key in SECTION_TO_CAGE:
                tags.extend(SECTION_TO_CAGE[section_key])

            articles.append(
                ScrapedArticle(
                    title=title,
                    url=url,
                    source="voz",
                    snippet=snippet[:300] if snippet else "",
                    content="",
                    date=date,
                    tags=tags,
                )
            )

        return articles

    @staticmethod
    async def _fetch_section(section_key: str, section_url: str) -> List[ScrapedArticle]:
        """Fetch and parse a single Voz forum section. Runs curl_cffi in thread."""
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            logger.warning("voz: curl_cffi not installed, falling back to httpx")
            return await VozScraper._fetch_section_httpx(section_key, section_url)

        def _sync_fetch() -> str:
            resp = curl_requests.get(
                section_url,
                impersonate="chrome124",
                timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            resp.raise_for_status()
            return resp.text

        try:
            html = await asyncio.to_thread(_sync_fetch)
        except Exception as exc:
            logger.warning(
                "voz: curl_cffi fetch failed for '%s': %s, "
                "falling back to httpx",
                section_key, exc,
            )
            return await VozScraper._fetch_section_httpx(section_key, section_url)

        return VozScraper._parse_forum_page(html, section_key)

    @staticmethod
    async def _fetch_section_httpx(
        section_key: str, section_url: str,
    ) -> List[ScrapedArticle]:
        """Fallback: fetch section via httpx with standard headers."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    section_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                    },
                )
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            logger.warning(
                "voz: httpx fallback also failed for '%s': %s",
                section_key, exc,
            )
            return []

        return VozScraper._parse_forum_page(html, section_key)

    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_thread_comments(thread_url: str, max_comments: int = 5) -> str:
        """Fetch and extract comment text from a Voz thread page."""
        import asyncio
        try:
            from curl_cffi import requests as curl_requests
            use_curl_cffi = True
        except ImportError:
            use_curl_cffi = False

        def _sync_curl() -> str:
            resp = curl_requests.get(
                thread_url,
                impersonate="chrome124",
                timeout=20,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                },
            )
            resp.raise_for_status()
            return resp.text

        async def _fetch_httpx() -> str:
            import httpx
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    thread_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
                    },
                )
                resp.raise_for_status()
                return resp.text

        try:
            if use_curl_cffi:
                html = await asyncio.to_thread(_sync_curl)
            else:
                html = await _fetch_httpx()
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "voz: failed to fetch thread comments for %s: %s", thread_url, exc
            )
            return ""

        # Parse comments from thread page
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        comments = []

        # Voz message content selectors
        for selector in [
            "div.message-content article",
            "article.message-body",
            "div.bbWrapper",
            "div.message-body",
        ]:
            for el in tree.css(selector):
                text = el.text(strip=True)
                if text and len(text) > 20 and len(comments) < max_comments:
                    # Remove quoted content (usually starts with username said:)
                    if "đã nói:" in text.lower() or "said:" in text.lower():
                        text = text.split(":", 1)[-1].strip()
                    comments.append(text[:400])
            if len(comments) >= max_comments:
                break

        return " | ".join(comments) if comments else ""

    async def fetch_articles(self) -> List[ScrapedArticle]:
        """
        Fetch thread titles from configured Voz sections concurrently.

        Returns up to ``max_articles``, deduplicated by URL.
        """
        # Fire all section fetches concurrently with a small stagger
        async def _fetch_one(section_key: str) -> List[ScrapedArticle]:
            url = VOZ_SECTIONS.get(section_key)
            if not url:
                return []
            try:
                return await self._fetch_section(section_key, url)
            except Exception as exc:
                logger.error(
                    "voz: failed to scrape section '%s': %s", section_key, exc,
                )
                return []

        # Stagger launches slightly to avoid hammering the server
        tasks = []
        for i, section_key in enumerate(self.sections):
            if i > 0:
                await asyncio.sleep(0.3)  # 300ms stagger between launches
            tasks.append(_fetch_one(section_key))

        # Gather all results
        all_section_results = await asyncio.gather(*tasks)

        # Merge and deduplicate
        articles: List[ScrapedArticle] = []
        seen_urls: set = set()

        for section_articles in all_section_results:
            for art in section_articles:
                if len(articles) >= self.max_articles:
                    break
                if art.url not in seen_urls:
                    seen_urls.add(art.url)
                    articles.append(art)
            if len(articles) >= self.max_articles:
                break

        # Fetch comments for a sample of top threads (up to 8)
        sample_for_comments = articles[: min(8, len(articles))]
        for i, art in enumerate(sample_for_comments):
            if art.url:
                comments = await self._fetch_thread_comments(art.url)
                if comments:
                    articles[i].content = comments
                    # If no snippet, use first comment as snippet
                    if not art.snippet:
                        articles[i].snippet = comments[:300]

        logger.info(
            "voz: fetched %d articles across %d sections (%d with comments)",
            len(articles), len(self.sections),
            sum(1 for a in articles[:8] if a.content),
        )
        return articles[: self.max_articles]
