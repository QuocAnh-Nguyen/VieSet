"""
Base scraper infrastructure for the CAGE dynamic content pipeline.

Provides:
- ``BaseScraper``: async scraper with httpx, retry, and graceful fallback
- ``ScraperCache``: lightweight JSONL cache to avoid re-fetching on reruns
- ``get_shared_http_client``: singleton httpx.AsyncClient for connection reuse

All scrapers inherit from BaseScraper and implement ``fetch_articles()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared HTTP client (connection reuse)
# ---------------------------------------------------------------------------

_shared_client: Optional[httpx.AsyncClient] = None


def get_shared_http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Return a module-level singleton ``httpx.AsyncClient``."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=10),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            },
        )
    return _shared_client


async def close_shared_client() -> None:
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ScrapedArticle:
    """Normalized article representation across all sources."""

    title: str
    url: str
    source: str  # e.g. "vnexpress", "voz", "thuvienphapluat"
    snippet: str = ""
    content: str = ""
    date: str = ""
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class ScraperCache:
    """
    Lightweight JSONL cache for scraper results.

    Each source gets its own cache file.  On a rerun, cached articles
    are returned immediately; fresh fetches are appended.
    """

    def __init__(self, cache_dir: str = "data/scraper_cache") -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str) -> Path:
        return self.cache_dir / f"{source}_cache.jsonl"

    def load(self, source: str) -> List[Dict[str, Any]]:
        """Load all cached articles for a source."""
        path = self._path(source)
        if not path.exists():
            return []
        items: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
        return items

    def save(self, source: str, articles: List[Dict[str, Any]]) -> None:
        """Append new articles to the source's cache file."""
        path = self._path(source)
        with open(path, "a", encoding="utf-8") as f:
            for art in articles:
                f.write(json.dumps(art, ensure_ascii=False) + "\n")

    def get_urls(self, source: str) -> set:
        """Return set of cached URLs to skip re-fetching."""
        return {a["url"] for a in self.load(source) if "url" in a}

    def clear(self, source: str) -> None:
        """Delete cache for a source."""
        path = self._path(source)
        if path.exists():
            path.unlink()


# ---------------------------------------------------------------------------
# Base Scraper
# ---------------------------------------------------------------------------
class BaseScraper(ABC):
    """
    Abstract base class for all content scrapers.

    Subclasses must implement ``fetch_articles()`` and set ``source_name``.
    The base class handles retry logic, HTTP client management, and caching.

    Parameters
    ----------
    cache : ScraperCache, optional
        Shared cache instance.  Created automatically if omitted.
    max_articles : int
        Maximum articles to return per run (default 50).
    """

    source_name: str = "base"  # override in subclass

    def __init__(
        self,
        cache: Optional[ScraperCache] = None,
        max_articles: int = 50,
    ) -> None:
        self.cache = cache or ScraperCache()
        self.max_articles = max_articles

    # ------------------------------------------------------------------
    # Retry wrapper
    # ------------------------------------------------------------------
    async def _fetch_with_retry(
        self,
        url: str,
        *,
        max_retries: int = 3,
        backoff: float = 2.0,
        **kwargs: Any,
    ) -> httpx.Response:
        """GET *url* with exponential backoff retry."""
        client = get_shared_http_client()
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = await client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exc = exc
                status = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else "network"
                )
                if attempt < max_retries:
                    sleep_s = backoff ** attempt
                    logger.warning(
                        "%s: attempt %d/%d failed (status=%s), "
                        "retrying in %.1fs: %s",
                        self.source_name, attempt, max_retries,
                        status, sleep_s, url,
                    )
                    await asyncio.sleep(sleep_s)
                else:
                    logger.error(
                        "%s: all %d attempts exhausted for %s: %s",
                        self.source_name, max_retries, url, exc,
                    )

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Abstract fetch method
    # ------------------------------------------------------------------
    @abstractmethod
    async def fetch_articles(self) -> List[ScrapedArticle]:
        """
        Fetch articles from the source.

        Returns list of ``ScrapedArticle`` (up to ``max_articles``).
        """
        ...

    # ------------------------------------------------------------------
    # Cached fetch (public API)
    # ------------------------------------------------------------------
    async def get_articles(
        self,
        force_refresh: bool = False,
    ) -> List[ScrapedArticle]:
        """
        Return articles, using cache when available.

        Parameters
        ----------
        force_refresh : bool
            If True, bypass cache and re-fetch everything.

        Returns
        -------
        List of ``ScrapedArticle`` (up to ``max_articles``).
        """
        if not force_refresh:
            cached = self.cache.load(self.source_name)
            if cached:
                logger.info(
                    "%s: returning %d cached articles",
                    self.source_name, len(cached),
                )
                return [
                    ScrapedArticle(
                        title=a.get("title", ""),
                        url=a.get("url", ""),
                        source=a.get("source", self.source_name),
                        snippet=a.get("snippet", ""),
                        content=a.get("content", ""),
                        date=a.get("date", ""),
                        tags=a.get("tags", []),
                    )
                    for a in cached[: self.max_articles]
                ]

        # Fetch fresh
        try:
            articles = await self.fetch_articles()
        except Exception as exc:
            logger.error(
                "%s: fetch failed, falling back to cache: %s",
                self.source_name, exc,
            )
            cached = self.cache.load(self.source_name)
            if cached:
                return [
                    ScrapedArticle(
                        title=a.get("title", ""),
                        url=a.get("url", ""),
                        source=a.get("source", self.source_name),
                        snippet=a.get("snippet", ""),
                        content=a.get("content", ""),
                        date=a.get("date", ""),
                        tags=a.get("tags", []),
                    )
                    for a in cached[: self.max_articles]
                ]
            return []  # nothing cached either → empty

        # Save to cache
        raw = [
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "snippet": a.snippet,
                "content": a.content,
                "date": a.date,
                "tags": a.tags,
            }
            for a in articles
        ]
        self.cache.save(self.source_name, raw)
        logger.info(
            "%s: saved %d articles to cache", self.source_name, len(articles),
        )
        return articles
