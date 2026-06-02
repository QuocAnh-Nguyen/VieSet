"""
LLM-based Auto-Labeling pipeline for mapping arbitrary seed categories
(e.g. HarmBench, BeaverTails) to the CAGE taxonomy (A-L).

Replaces the flawed ``c.strip()[0].upper()`` string-slicing approach with
an LLM-driven mapping that understands semantic category equivalence.

Design:
- For each unique source category, send a mapping prompt to the LLM
- Cache results to avoid redundant API calls on reruns
- Fall back to heuristic matching if LLM is unavailable
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CAGE Taxonomy reference (A-L) with Vietnamese descriptions
# ---------------------------------------------------------------------------
CAGE_TAXONOMY_REFERENCE: Dict[str, Dict[str, str]] = {
    "A": {
        "code": "A",
        "name_en": "Toxic Language",
        "name_vn": "Ngon ngu Doc hai",
        "description": "Harassment, offensive language, slurs, cyberbullying, "
                       "hate speech targeting individuals or groups.",
        "harmbench_categories": "harassment, hate, insults, toxic language, offensive",
    },
    "B": {
        "code": "B",
        "name_en": "Sexual Content",
        "name_vn": "Noi dung Khieu dam",
        "description": "Adult content, erotic material, monetized sexual "
                       "services, pornography, sexual exploitation.",
        "harmbench_categories": "sexual, adult content, erotic, pornography",
    },
    "C": {
        "code": "C",
        "name_en": "Discrimination",
        "name_vn": "Phan biet Doi xu",
        "description": "Unfair treatment based on identity: characterization, "
                       "classification, discriminatory activities.",
        "harmbench_categories": "discrimination, unfair treatment, identity bias",
    },
    "D": {
        "code": "D",
        "name_en": "Bias and Hate",
        "name_vn": "Dinh kien va Thu ghet",
        "description": "Prejudice based on age, beliefs, color, disability, "
                       "ethnicity, gender, nationality, occupation, religion.",
        "harmbench_categories": "bias, hate, prejudice, stereotyping, racism, sexism",
    },
    "E": {
        "code": "E",
        "name_en": "Misinformation",
        "name_vn": "Thong tin Sai lech",
        "description": "False or misleading information: fake news, "
                       "conspiracy theories, disinformation, propaganda.",
        "harmbench_categories": "misinformation, disinformation, fake news, "
                                "conspiracy, propaganda",
    },
    "F": {
        "code": "F",
        "name_en": "Prohibited Advisory",
        "name_vn": "Tu van Bi cam",
        "description": "Unauthorized professional advice: legal, medical, "
                       "financial, or other regulated domains.",
        "harmbench_categories": "legal advice, medical advice, financial advice, "
                                "unauthorized consulting",
    },
    "G": {
        "code": "G",
        "name_en": "Privacy Violation",
        "name_vn": "Xam pham Quyen rieng tu",
        "description": "Unauthorized access to private information, doxxing, "
                       "surveillance, stalking, data breaches.",
        "harmbench_categories": "privacy, doxxing, surveillance, data breach, stalking",
    },
    "H": {
        "code": "H",
        "name_en": "Sensitive Organizational Information",
        "name_vn": "Thong tin Nhạy cam cua To chuc",
        "description": "Disclosure of classified, proprietary, or internal "
                       "organizational information.",
        "harmbench_categories": "trade secrets, classified, internal documents, "
                                "proprietary information",
    },
    "I": {
        "code": "I",
        "name_en": "Illegal Activities",
        "name_vn": "Hoat dong Bat hop phap",
        "description": "Facilitating crimes: fraud, scams, illegal services, "
                       "exploitation, drug trafficking.",
        "harmbench_categories": "illegal, fraud, scams, crime, drugs, exploitation",
    },
    "J": {
        "code": "J",
        "name_en": "Violence and Extremism",
        "name_vn": "Bao luc va Cuc doan",
        "description": "Depicting violence, supporting extremist groups, "
                       "violent crimes, terrorism.",
        "harmbench_categories": "violence, extremism, terrorism, weapons, harm",
    },
    "K": {
        "code": "K",
        "name_en": "Unethical Actions",
        "name_vn": "Khuyen khich Hanh vi Phi dao duc",
        "description": "Cheating, dishonesty, defamation, manipulation, "
                       "corruption, academic fraud.",
        "harmbench_categories": "unethical, cheating, defamation, manipulation, "
                                "corruption, dishonesty",
    },
    "L": {
        "code": "L",
        "name_en": "Security Threats",
        "name_vn": "De doa An ninh",
        "description": "Cyber attacks, malware, weapon development, "
                       "security exploits, hacking.",
        "harmbench_categories": "cyber, malware, hacking, security, weapons, exploit",
    },
}

# ---------------------------------------------------------------------------
# Heuristic fallback mapping: source category keywords -> CAGE code
# ---------------------------------------------------------------------------
HEURISTIC_MAP: Dict[str, str] = {
    "harassment": "A",
    "harass": "A",
    "hate": "D",
    "toxic": "A",
    "insult": "A",
    "offensive": "A",
    "slur": "A",
    "sexual": "B",
    "adult": "B",
    "erotic": "B",
    "porn": "B",
    "discrimination": "C",
    "discrim": "C",
    "unfair": "C",
    "bias": "D",
    "prejudice": "D",
    "stereotype": "D",
    "racism": "D",
    "sexism": "D",
    "misinformation": "E",
    "disinformation": "E",
    "fake": "E",
    "conspiracy": "E",
    "propaganda": "E",
    "legal": "F",
    "medical": "F",
    "financial": "F",
    "advice": "F",
    "privacy": "G",
    "doxxing": "G",
    "surveillance": "G",
    "stalking": "G",
    "data": "G",
    "trade": "H",
    "classified": "H",
    "proprietary": "H",
    "internal": "H",
    "illegal": "I",
    "fraud": "I",
    "scam": "I",
    "crime": "I",
    "drug": "I",
    "exploit": "I",
    "violence": "J",
    "extremism": "J",
    "terror": "J",
    "weapon": "J",
    "harm": "J",
    "unethical": "K",
    "cheat": "K",
    "defamation": "K",
    "manipulation": "K",
    "corruption": "K",
    "dishonest": "K",
    "cyber": "L",
    "malware": "L",
    "hacking": "L",
    "security": "L",
    "exploit": "L",
}

# ---------------------------------------------------------------------------
# LLM AUTO-LABELER PROMPT
# ---------------------------------------------------------------------------
AUTO_LABEL_SYSTEM = """[Instructions]
You are an expert in AI safety taxonomies. Your task is to map a given
red-teaming prompt category to the correct CAGE taxonomy code.

[CAGE Taxonomy Reference]
- A: Toxic Language (hate speech, harassment, slurs, cyberbullying)
- B: Sexual Content (adult, erotic, pornography, sexual exploitation)
- C: Discrimination (unfair treatment based on identity)
- D: Bias and Hate (prejudice based on age, race, gender, religion, etc.)
- E: Misinformation (fake news, conspiracy theories, disinformation)
- F: Prohibited Advisory (unauthorized legal/medical/financial advice)
- G: Privacy Violation (doxxing, surveillance, data breaches)
- H: Sensitive Org Information (trade secrets, classified documents)
- I: Illegal Activities (fraud, scams, crime, drugs, exploitation)
- J: Violence and Extremism (terrorism, weapons, violent crimes)
- K: Unethical Actions (cheating, defamation, manipulation, corruption)
- L: Security Threats (cyber attacks, malware, hacking, exploits)

[Task]
Given a source category name and optional prompt text, output the SINGLE
LETTER code (A-L) that best matches the CAGE taxonomy.

[Output Format]
Return JSON: {"cage_code": "X", "confidence": "high|medium|low", "rationale": "brief explanation"}"""


class AutoLabeler:
    """
    LLM-based mapper from arbitrary category names to CAGE taxonomy codes (A-L).

    Uses the project's ``LLMClient`` for mapping; falls back to keyword heuristics
    if the client is unavailable or confidence is low.

    Parameters
    ----------
    client : LLMClient, optional
        If None, only heuristic matching is used.
    cache_path : str, optional
        Path to JSON cache file for label mappings.
    """

    def __init__(
        self,
        client: Optional[object] = None,  # LLMClient
        cache_path: str = "data/auto_label_cache.json",
    ) -> None:
        self.client = client
        self.cache_path = Path(cache_path)
        self._cache: Dict[str, Dict[str, str]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                logger.debug("Loaded %d cached label mappings", len(self._cache))
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Heuristic fallback (no LLM needed)
    # ------------------------------------------------------------------
    @staticmethod
    def heuristic_map(category_name: str, prompt_text: str = "") -> Tuple[str, str]:
        """
        Keyword-based heuristic mapping from source category to CAGE code.

        Returns (cage_code, rationale).
        """
        normalized = category_name.lower().strip()

        # Direct match by first letter if it's already A-L format
        if len(normalized) == 1 and normalized.upper() in set("ABCDEFGHIJKL"):
            return normalized.upper(), "exact single-letter match"

        # Check for CAGE format "A. Ngon ngu Doc hai" etc.
        if normalized and normalized[0].upper() in set("ABCDEFGHIJKL"):
            first = normalized[0].upper()
            # Verify it looks like a CAGE-formatted string
            if "." in normalized[:3]:
                return first, "CAGE-format string match"

        # Keyword scanning
        scores: Dict[str, int] = {}
        combined = f"{normalized} {prompt_text.lower()}" if prompt_text else normalized

        for keyword, code in HEURISTIC_MAP.items():
            if keyword in combined:
                scores[code] = scores.get(code, 0) + 1

        if scores:
            best_code = max(scores, key=scores.get)
            matched_keywords = [k for k, c in HEURISTIC_MAP.items()
                                if c == best_code and k in combined]
            return best_code, f"keyword match: {', '.join(matched_keywords[:3])}"

        # Default fallback: use first-letter if between A-L
        first_char = normalized[0].upper() if normalized else ""
        if first_char in set("ABCDEFGHIJKL"):
            return first_char, "first-letter heuristic (low confidence)"

        return "A", "no match; defaulting to A"

    # ------------------------------------------------------------------
    # LLM-based mapping (async)
    # ------------------------------------------------------------------
    async def _llm_map(self, category_name: str, prompt_text: str = "") -> Tuple[str, str]:
        """Use LLMClient to map a category to CAGE code."""
        user_prompt = (
            f"Source Category: \"{category_name}\"\n"
            f"Sample Prompt Text: \"{prompt_text[:200]}\"\n\n"
            "Map this to the single-letter CAGE taxonomy code (A-L)."
        )

        try:
            raw = await self.client.agenerate_json(
                input_text=user_prompt,
                system_prompt=AUTO_LABEL_SYSTEM,
                temperature=0.1,
                max_tokens=256,
            )
            from generate.base.llm_client import strip_markdown_wrapper
            cleaned = strip_markdown_wrapper(raw)
            data = json.loads(cleaned)
            code = data.get("cage_code", "A").strip().upper()
            confidence = data.get("confidence", "low")
            rationale = data.get("rationale", "LLM mapping")

            # Validate code is A-L
            if code not in set("ABCDEFGHIJKL"):
                logger.warning("LLM returned invalid code '%s', falling back to heuristic", code)
                return AutoLabeler.heuristic_map(category_name, prompt_text)

            # If confidence is low, also check heuristic
            if confidence == "low":
                heur_code, heur_rationale = AutoLabeler.heuristic_map(category_name, prompt_text)
                if heur_code != code:
                    logger.info(
                        "LLM low-confidence (%s) vs heuristic (%s) for '%s'. Using heuristic.",
                        code, heur_code, category_name,
                    )
                    return heur_code, f"heuristic override: {heur_rationale}"

            return code, f"LLM: {rationale}"

        except Exception as exc:
            logger.warning("LLM auto-labeling failed: %s. Falling back to heuristic.", exc)
            return AutoLabeler.heuristic_map(category_name, prompt_text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def map_category(
        self,
        category_name: str,
        prompt_text: str = "",
        force_refresh: bool = False,
    ) -> Tuple[str, str]:
        """
        Map a source category name to a CAGE taxonomy code (A-L).

        Uses cached LLM results when available; falls back to heuristics.

        Parameters
        ----------
        category_name : str
            The source category label (e.g., "harassment", "sexual", "fake news").
        prompt_text : str
            Optional sample prompt to disambiguate the category.
        force_refresh : bool
            If True, bypass cache and re-query.

        Returns
        -------
        (cage_code, rationale) tuple.
        """
        cache_key = category_name.strip().lower()

        if not force_refresh and cache_key in self._cache:
            entry = self._cache[cache_key]
            return entry["code"], entry.get("rationale", "cached")

        if self.client is not None:
            code, rationale = await self._llm_map(category_name, prompt_text)
        else:
            code, rationale = self.heuristic_map(category_name, prompt_text)

        # Cache the result
        self._cache[cache_key] = {"code": code, "rationale": rationale}
        self._save_cache()

        return code, rationale

    async def map_dataframe(
        self,
        categories: List[str],
        prompts: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[Tuple[str, str]]:
        """
        Map a list of category names to CAGE codes in bulk.

        Returns list of (cage_code, rationale) tuples in original order.
        """
        results: List[Tuple[str, str]] = []
        for i, cat in enumerate(categories):
            prompt = prompts[i] if prompts and i < len(prompts) else ""
            result = await self.map_category(cat, prompt, force_refresh)
            results.append(result)
        return results
