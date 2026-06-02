"""
LLM-based Auto-Labeling pipeline for mapping arbitrary seed categories
(e.g. HarmBench, BeaverTails) to the CAGE taxonomy (A-L) and Level-3 types.

Replaces the flawed ``c.strip()[0].upper()`` string-slicing approach with
an LLM-driven mapping that understands semantic category equivalence.

Phase 3: Now also predicts Level-3 type names for precise Semantic Mold selection.

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
        "description": "Cyber attacks, malware generation, weapon development, "
                       "system exploits, security vulnerabilities.",
        "harmbench_categories": "cyber attack, malware, hacking, exploits, "
                                "weapons, security",
    },
}

# ---------------------------------------------------------------------------
# Heuristic keyword mapping (fallback when LLM is unavailable)
# ---------------------------------------------------------------------------
HEURISTIC_MAP: Dict[str, str] = {
    "harass": "A", "hate": "A", "toxic": "A", "slur": "A", "insult": "A",
    "offensive": "A", "cyberbully": "A", "bully": "A",
    "sexual": "B", "adult": "B", "erotic": "B", "porn": "B", "sex": "B",
    "discriminat": "C", "unfair": "C", "identity": "C",
    "bias": "D", "prejudice": "D", "stereotype": "D", "racis": "D", "sexis": "D",
    "misinformation": "E", "disinformation": "E", "fake news": "E",
    "conspiracy": "E", "propaganda": "E", "rumor": "E",
    "legal advice": "F", "medical advice": "F", "financial advice": "F",
    "prohibited": "F", "unauthorized": "F",
    "privacy": "G", "doxx": "G", "surveillance": "G", "data breach": "G",
    "trade secret": "H", "classified": "H", "proprietary": "H",
    "illegal": "I", "fraud": "I", "scam": "I", "crime": "I", "drug": "I",
    "violence": "J", "extremis": "J", "terror": "J", "weapon": "J",
    "unethical": "K", "cheat": "K", "defam": "K", "manipulat": "K", "corrupt": "K",
    "cyber": "L", "malware": "L", "hack": "L", "exploit": "L",
}

# ---------------------------------------------------------------------------
# Build Level-3 type reference from molds.py (kept in sync at runtime)
# ---------------------------------------------------------------------------
def _build_type_reference() -> str:
    """Build a Level-3 type reference string from CATEGORY_SLOTS."""
    try:
        from .template.molds import CATEGORY_SLOTS
        lines = []
        for code in sorted(CATEGORY_SLOTS):
            cat = CATEGORY_SLOTS[code]
            types = list(cat["types"].keys())
            lines.append(
                f"  {code} ({cat['category']}): {', '.join(types)}"
            )
        return "\n".join(lines)
    except Exception:
        return "(Level-3 types unavailable)"


# ---------------------------------------------------------------------------
# LLM System Prompt for Auto-Labeling (Level-2 + Level-3)
# ---------------------------------------------------------------------------
_AUTO_LABEL_SYSTEM_BASE = """[Instructions]
You are an expert in AI safety taxonomies. Your task is to map a given
red-teaming prompt category to the correct CAGE taxonomy Level-2 code (A-L)
AND the most appropriate Level-3 type within that category.

[CAGE Taxonomy Reference - Level 2]
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

[CAGE Taxonomy Reference - Level 3 Types per Category]
<<<TYPE_REFERENCE>>>

[Task]
Given a source category name and optional prompt text, output:
1. The SINGLE LETTER Level-2 code (A-L) that best matches
2. The EXACT Level-3 type name from the list above
3. A confidence level

Choose the Level-3 type that best describes the specific nature of the
prompt. For category E (Misinformation) determine whether it is
"False News", "Rumors", "Propaganda", or "Misinterpretation or Wrong Context".

[Output Format]
Return JSON with fields: cage_code, type_name, confidence, rationale"""


def _get_auto_label_system() -> str:
    """Build the system prompt with live type reference."""
    type_ref = _build_type_reference()
    return _AUTO_LABEL_SYSTEM_BASE.replace("<<<TYPE_REFERENCE>>>", type_ref)

# Alias kept for backward compatibility - resolved at call time
AUTO_LABEL_SYSTEM = None  # resolved dynamically


class AutoLabeler:
    """
    LLM-based mapper from arbitrary category names to CAGE taxonomy codes (A-L)
    and Level-3 types.

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
            if len(normalized) > 1 and normalized[1] in (".", " ", "-"):
                return normalized[0].upper(), "CAGE-format prefix match"

        # Keyword-based scoring
        scores: Dict[str, int] = {}
        combined = normalized + " " + (prompt_text or "").lower().strip()
        if prompt_text:
            combined = normalized + " " + prompt_text.lower().strip()
        else:
            combined = normalized

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
    # LLM-based mapping (async) - now returns (code, type_name, rationale)
    # ------------------------------------------------------------------
    async def _llm_map(self, category_name: str, prompt_text: str = "") -> Tuple[str, str, str]:
        """Use LLMClient to map a category to CAGE code and Level-3 type."""
        user_prompt = (
            f"Source Category: \"{category_name}\"\n"
            f"Sample Prompt Text: \"{prompt_text[:200]}\"\n\n"
            "Map this to the single-letter CAGE taxonomy code (A-L) and the "
            "exact Level-3 type name."
        )

        system_prompt = _get_auto_label_system()

        try:
            raw = await self.client.agenerate_json(
                input_text=user_prompt,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=256,
            )
            from generate.base.llm_client import strip_markdown_wrapper
            cleaned = strip_markdown_wrapper(raw)
            data = json.loads(cleaned)
            code = data.get("cage_code", "A").strip().upper()
            type_name = data.get("type_name", "").strip()
            confidence = data.get("confidence", "low")
            rationale = data.get("rationale", "LLM mapping")

            # Validate code is A-L
            if code not in set("ABCDEFGHIJKL"):
                logger.warning("LLM returned invalid code '%s', falling back to heuristic", code)
                heur_code, heur_rationale = AutoLabeler.heuristic_map(category_name, prompt_text)
                return heur_code, "", f"heuristic fallback (invalid LLM code): {heur_rationale}"

            # Validate type_name against known types
            if type_name:
                from .template.molds import CATEGORY_SLOTS
                known_types = list(CATEGORY_SLOTS.get(code, {}).get("types", {}).keys())
                if type_name not in known_types:
                    logger.warning(
                        "LLM returned unknown type_name '%s' for code '%s'. Known: %s. "
                        "Falling back to first type.",
                        type_name, code, known_types,
                    )
                    type_name = known_types[0] if known_types else ""

            # If confidence is low, also check heuristic
            if confidence == "low":
                heur_code, heur_rationale = AutoLabeler.heuristic_map(category_name, prompt_text)
                if heur_code != code:
                    logger.info(
                        "LLM low-confidence (%s) vs heuristic (%s) for '%s'. Using heuristic.",
                        code, heur_code, category_name,
                    )
                    return heur_code, "", f"heuristic override: {heur_rationale}"

            return code, type_name, f"LLM: {rationale}"

        except Exception as exc:
            logger.warning("LLM auto-labeling failed: %s. Falling back to heuristic.", exc)
            heur_code, heur_rationale = AutoLabeler.heuristic_map(category_name, prompt_text)
            return heur_code, "", f"heuristic fallback: {heur_rationale}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def map_category(
        self,
        category_name: str,
        prompt_text: str = "",
        force_refresh: bool = False,
    ) -> Tuple[str, str, str]:
        """
        Map a source category name to a CAGE taxonomy code (A-L) and Level-3 type.

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
        (cage_code, type_name, rationale) tuple.
        """
        cache_key = category_name.strip().lower()

        if not force_refresh and cache_key in self._cache:
            entry = self._cache[cache_key]
            return entry["code"], entry.get("type_name", ""), entry.get("rationale", "cached")

        if self.client is not None:
            code, type_name, rationale = await self._llm_map(category_name, prompt_text)
        else:
            code, rationale = self.heuristic_map(category_name, prompt_text)
            type_name = ""

        # Cache the result
        self._cache[cache_key] = {"code": code, "type_name": type_name, "rationale": rationale}
        self._save_cache()

        return code, type_name, rationale

    async def map_dataframe(
        self,
        categories: List[str],
        prompts: Optional[List[str]] = None,
        force_refresh: bool = False,
    ) -> List[Tuple[str, str, str]]:
        """
        Map a list of category names to CAGE codes and Level-3 types in bulk.

        Returns list of (cage_code, type_name, rationale) tuples in original order.
        """
        results: List[Tuple[str, str, str]] = []
        for i, cat in enumerate(categories):
            prompt = prompts[i] if prompts and i < len(prompts) else ""
            result = await self.map_category(cat, prompt, force_refresh)
            results.append(result)
        return results
