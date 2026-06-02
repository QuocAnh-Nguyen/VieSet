# Generate / Scraping module

from .base import BaseScraper, ScraperCache, get_shared_http_client
from .vnexpress import VnExpressScraper
from .voz import VozScraper
from .thuvienphapluat import ThuVienPhapLuatScraper

__all__ = [
    "BaseScraper",
    "ScraperCache",
    "get_shared_http_client",
    "VnExpressScraper",
    "VozScraper",
    "ThuVienPhapLuatScraper",
]
