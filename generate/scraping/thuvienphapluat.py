# -*- coding: utf-8 -*-
"""
Thu vien Phap luat (thuvienphapluat.vn) scraper for taxonomy-driven content.

Covers Vietnamese legal codes referenced throughout the CAGE taxonomy:
Criminal Code (Categories I,J,K,L), Cybersecurity Law (L,G),
Civil Code (G,K), Gender Equality Law (C,D), Anti-Corruption (K), etc.

Falls back to hard-coded law snippets if the website blocks scraping.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from selectolax.parser import HTMLParser

from .base import BaseScraper, ScrapedArticle, ScraperCache, get_shared_http_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legal pages: each CAGE category maps to a search URL on thuvienphapluat.vn
# ---------------------------------------------------------------------------
LEGAL_PAGES: Dict[str, Dict[str, object]] = {
    "A": {
        "label": "Bo luat Hinh su - Xuc pham",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=x%C3%BAc+ph%E1%BA%A1m+danh+d%E1%BB%B1+nh%C3%A2n+ph%E1%BA%A9m",
        "hint": ["xuc pham danh du", "nhan pham", "Dieu 155"],
    },
    "B": {
        "label": "Bo luat Hinh su - Toi pham tinh duc",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=t%E1%BB%99i+ph%E1%BA%A1m+t%C3%ACnh+d%E1%BB%A5c",
        "hint": ["toi pham tinh duc", "van hoa pham doi truy", "Dieu 326"],
    },
    "C": {
        "label": "Luat Binh dang gioi - Phan biet doi xu",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=ph%C3%A2n+bi%E1%BB%87t+%C4%91%E1%BB%91i+x%E1%BB%AD",
        "hint": ["phan biet doi xu", "binh dang gioi", "lao dong nu"],
    },
    "E": {
        "label": "Luat An ninh mang - Tin gia",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=tin+gi%E1%BA%A3",
        "hint": ["tin gia", "thong tin sai su that", "mang xa hoi"],
    },
    "F": {
        "label": "Xu phat hanh chinh - Tu van trai phep",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=x%E1%BB%AD+ph%E1%BA%A1t+h%C3%A0nh+ch%C3%ADnh+y+t%E1%BA%BF",
        "hint": ["tu van trai phep", "hanh nghe khong phep", "y te"],
    },
    "G": {
        "label": "Luat An ninh mang - Quyen rieng tu",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=quy%E1%BB%81n+ri%C3%AAng+t%C6%B0",
        "hint": ["quyen rieng tu", "du lieu ca nhan", "bao mat thong tin"],
    },
    "H": {
        "label": "Luat Bao ve bi mat nha nuoc",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=b%C3%AD+m%E1%BA%ADt+nh%C3%A0+n%C6%B0%E1%BB%9Bc",
        "hint": ["bi mat nha nuoc", "thong tin mat", "tai lieu mat"],
    },
    "I": {
        "label": "Bo luat Hinh su - Lua dao chiem doat tai san",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=l%E1%BB%ABa+%C4%91%E1%BA%A3o+chi%E1%BA%BFm+%C4%91o%E1%BA%A1t+t%C3%A0i+s%E1%BA%A3n",
        "hint": ["lua dao", "chiem doat tai san", "danh bac", "rua tien"],
    },
    "J": {
        "label": "Bo luat Hinh su - Bao luc va khung bo",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=t%E1%BB%99i+gi%E1%BA%BFt+ng%C6%B0%E1%BB%9Di",
        "hint": ["giet nguoi", "co y gay thuong tich", "khung bo", "Dieu 123"],
    },
    "K": {
        "label": "Luat Phong chong tham nhung",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=tham+nh%C5%A9ng",
        "hint": ["tham nhung", "hoi lo", "gian lan", "tron thue", "dao van"],
    },
    "L": {
        "label": "Luat An ninh mang - Toi pham cong nghe",
        "url": "https://thuvienphapluat.vn/hoi-dap-phap-luat/tim-kiem?keyword=t%E1%BB%99i+ph%E1%BA%A1m+m%E1%BA%A1ng",
        "hint": ["an ninh mang", "tan cong mang", "xam nhap trai phep",
                 "virus", "malware", "ransomware", "danh cap du lieu"],
    },
}

# ---------------------------------------------------------------------------
# Fallback law snippets: used when the website blocks us
# ---------------------------------------------------------------------------
FALLBACK_LAWS: Dict[str, List[Dict[str, str]]] = {
    "A": [
        {"title": "Dieu 155 Bo luat Hinh su 2015 - Toi lam nhuc nguoi khac",
         "snippet": "Nguoi nao xuc pham nghiem trong nhan pham, danh du cua nguoi khac..."},
        {"title": "Dieu 156 Bo luat Hinh su 2015 - Toi vu khong",
         "snippet": "Nguoi nao bia dat hoac loan truyen nhung dieu biet ro la sai su that..."},
    ],
    "B": [
        {"title": "Dieu 326 Bo luat Hinh su 2015 - Truyen ba van hoa pham doi truy",
         "snippet": "Nguoi nao lam ra, sao chep, luu hanh, van chuyen, mua ban..."},
    ],
    "C": [
        {"title": "Luat Binh dang gioi 2006 - Dieu 5",
         "snippet": "Cam phan biet doi xu ve gioi duoi moi hinh thuc..."},
    ],
    "E": [
        {"title": "Luat An ninh mang 2018 - Dieu 8",
         "snippet": "Cam dua thong tin sai su that, xuyen tac len khong gian mang..."},
    ],
    "G": [
        {"title": "Luat An ninh mang 2018 - Dieu 26",
         "snippet": "Bao dam an toan thong tin ca nhan tren khong gian mang..."},
    ],
    "H": [
        {"title": "Luat Bao ve bi mat nha nuoc 2018",
         "snippet": "Quy dinh ve pham vi bi mat nha nuoc, bao ve bi mat nha nuoc..."},
    ],
    "I": [
        {"title": "Dieu 174 Bo luat Hinh su 2015 - Toi lua dao chiem doat tai san",
         "snippet": "Nguoi nao bang thu doan gian doi chiem doat tai san cua nguoi khac..."},
        {"title": "Dieu 321 Bo luat Hinh su 2015 - Toi danh bac",
         "snippet": "Nguoi nao danh bac trai phep duoi bat ky hinh thuc nao..."},
    ],
    "J": [
        {"title": "Dieu 123 Bo luat Hinh su 2015 - Toi giet nguoi",
         "snippet": "Nguoi nao giet nguoi thuoc mot trong cac truong hop..."},
        {"title": "Dieu 134 Bo luat Hinh su 2015 - Toi co y gay thuong tich",
         "snippet": "Nguoi nao co y gay thuong tich hoac gay ton hai cho suc khoe..."},
    ],
    "K": [
        {"title": "Luat Phong chong tham nhung 2018",
         "snippet": "Quy dinh ve phong ngua, phat hien, xu ly tham nhung..."},
        {"title": "Dieu 200 Bo luat Hinh su 2015 - Toi tron thue",
         "snippet": "Nguoi nao tron thue voi so tien tu 100 trieu dong tro len..."},
    ],
    "L": [
        {"title": "Dieu 289 Bo luat Hinh su 2015 - Xam nhap trai phep mang may tinh",
         "snippet": "Nguoi nao xam nhap trai phep vao mang may tinh, mang vien thong..."},
        {"title": "Luat An ninh mang 2018 - Dieu 18",
         "snippet": "Phong ngua, xu ly tinh huong nguy hiem ve an ninh mang..."},
    ],
}


class ThuVienPhapLuatScraper(BaseScraper):
    """Scrape thu vien phap luat for Vietnamese legal texts.

    Taxonomy-driven: each CAGE category maps to specific legal documents.

    Falls back to hard-coded law snippets when the website blocks scraping.
    """

    source_name = "thuvienphapluat"

    def __init__(
        self,
        cache: Optional[ScraperCache] = None,
        max_articles: int = 5,
        categories: Optional[List[str]] = None,
    ) -> None:
        super().__init__(cache=cache, max_articles=max_articles)
        self.categories = categories or list(LEGAL_PAGES.keys())

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_search_page(html: str, cat_code: str) -> List[ScrapedArticle]:
        """Parse a search results page from thuvienphapluat.vn."""
        articles: List[ScrapedArticle] = []
        tree = HTMLParser(html)

        for item in tree.css("div.result-item, div.search-item, li.result-item"):
            title_el = item.css_first("a.title, h3 a, a.result-title")
            if not title_el:
                title_el = item.css_first("a")
            if not title_el:
                continue

            title = title_el.text(strip=True)
            href = title_el.attributes.get("href", "")
            url = href if href.startswith("http") else "https://thuvienphapluat.vn" + href

            snippet_el = item.css_first("p.snippet, div.description, .excerpt")
            snippet = snippet_el.text(strip=True) if snippet_el else title

            page_info = LEGAL_PAGES.get(cat_code, {})
            hint_list = page_info.get("hint", [])
            if isinstance(hint_list, list):
                tags = [cat_code] + hint_list
            else:
                tags = [cat_code]

            articles.append(ScrapedArticle(
                title=title,
                url=url,
                source="thuvienphapluat",
                snippet=snippet[:400],
                content="",
                date="",
                tags=tags,
            ))

        return articles

    # ------------------------------------------------------------------
    async def fetch_articles(self) -> List[ScrapedArticle]:
        """Fetch legal texts for configured categories, with fallback."""
        client = get_shared_http_client()
        all_articles: List[ScrapedArticle] = []

        for cat_code in self.categories:
            page_info = LEGAL_PAGES.get(cat_code)
            if not page_info:
                continue

            url: str = page_info["url"]  # type: ignore[assignment]
            label: str = page_info["label"]  # type: ignore[assignment]
            hints_list = page_info.get("hint", [])

            try:
                resp = await self._fetch_with_retry(url, max_retries=2, backoff=1.5)
                parsed = self._parse_search_page(resp.text, cat_code)
                all_articles.extend(parsed[: self.max_articles])
                logger.debug(
                    "thuvienphapluat: fetched %d items for cat %s (%s)",
                    min(len(parsed), self.max_articles), cat_code, label,
                )
            except Exception as exc:
                logger.warning(
                    "thuvienphapluat: fetch failed for cat %s (%s): %s. Using fallback.",
                    cat_code, label, exc,
                )
                fallbacks = FALLBACK_LAWS.get(cat_code, [])
                tag_list: list = [cat_code]
                if isinstance(hints_list, list):
                    tag_list.extend(hints_list)
                for fb in fallbacks[: self.max_articles]:
                    all_articles.append(ScrapedArticle(
                        title=fb["title"],
                        url="",
                        source="thuvienphapluat",
                        snippet=fb["snippet"],
                        content="",
                        date="",
                        tags=tag_list,
                    ))

        logger.info(
            "thuvienphapluat: fetched %d total articles", len(all_articles),
        )
        return all_articles
