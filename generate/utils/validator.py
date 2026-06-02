"""
Output validation and filtering for the CAGE generation pipeline.

Ensures generated Vietnamese prompts meet quality standards:
- Minimum content length and Vietnamese character ratio
- Category consistency checks
- Deduplication
- Compatibility with the evaluate/ pipeline

Phase 2 fix: English-word check now excludes Vietnamese loanwords
(e.g. "video", "livestream", "app", "online", "Facebook", etc.).
"""

import re
import json
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Vietnamese-specific character set (Latin-based with diacritics)
VN_CHAR_PATTERN = re.compile(
    r'[a-zA-Z\xc0\xc1\xc2\xc3\xc8\xc9\xca\xcc\xcd\xd2\xd3\xd4\xd5\xd9\xda'
    r'\u0102\u0110\u0128\u0168\u01a0\xe0\xe1\xe2\xe3\xe8\xe9\xea\xec\xed'
    r'\xf2\xf3\xf4\xf5\xf9\xfa\u0103\u0111\u0129\u0169\u01a1'
    r'\u01af\u0102\u1ea0\u1ea2\u1ea4\u1ea6\u1ea8\u1eaa\u1eac\u1eae\u1eb0\u1eb2'
    r'\u1eb4\u1eb6\u1eb8\u1eba\u1ebc\u1ec0\u1ec0\u1ec2\u1ec4\u1ec6\u1ec8\u1eca'
    r'\u1ecc\u1ece\u1ed0\u1ed2\u1ed4\u1ed6\u1ed8\u1eda\u1edc\u1ede\u1ee0\u1ee2'
    r'\u1ee4\u1ee6\u1ee8\u1eea\u1eec\u1eee\u1ef0\u1ef2\u1ef4\u1ef6\u1ef8'
    r'\u01b0\u0103\u1ea1\u1ea3\u1ea5\u1ea7\u1ea9\u1eab\u1ead\u1eaf\u1eb1\u1eb3'
    r'\u1eb5\u1eb7\u1eb9\u1ebb\u1ebd\u1ec1\u1ec1\u1ec3\u1ec5\u1ec7\u1ec9\u1ecb'
    r'\u1ecd\u1ecf\u1ed1\u1ed3\u1ed5\u1ed7\u1ed9\u1edb\u1edd\u1edf\u1ee1\u1ee3'
    r'\u1ee5\u1ee7\u1ee9\u1eeb\u1eed\u1eef\u1ef1\u1ef3\u1ef5\u1ef7\u1ef9\s]'
)

# Minimum prompt length in characters
MIN_PROMPT_LENGTH = 20

# Maximum prompt length (to avoid excessively long generations)
MAX_PROMPT_LENGTH = 2000

# ---------------------------------------------------------------------------
# Vietnamese loanword whitelist (Phase 2 fix)
# Words below are commonly used in everyday Vietnamese text and should NOT
# be counted as "English" by the validator.
# ---------------------------------------------------------------------------
VN_LOANWORD_WHITELIST: set = {
    # Tech / Internet
    "video", "livestream", "stream", "app", "online", "offline",
    "website", "web", "link", "post", "share", "like", "comment",
    "chat", "sms", "wifi", "bluetooth", "usb", "sim", "card",
    "smartphone", "laptop", "tablet", "pc", "software", "hardware",
    "upload", "download", "login", "logout", "click", "copy",
    "paste", "email", "gmail", "facebook", "youtube", "tiktok",
    "zalo", "viber", "telegram", "instagram", "twitter",
    "messenger", "whatsapp", "snapchat", "wechat",
    # Business / Finance
    "bank", "atm", "visa", "mastercard", "momo", "zalopay",
    "shopee", "lazada", "tiki", "grab", "be", "now",
    "marketing", "ceo", "cfo", "staff", "team", "meeting",
    "report", "sale", "discount", "voucher", "order",
    # Common everyday
    "ok", "okay", "bye", "hello", "sorry", "thanks", "please",
    "sexy", "hot", "cool", "fan", "idol", "show", "live",
    "karaoke", "cafe", "bar", "club", "pub", "hotel", "resort",
    "buffet", "sushi", "pizza", "burger", "beefsteak", "beer",
    "wine", "cocktail", "coffee", "milk", "tea",
    # Medical / Health
    "covid", "virus", "test", "kit", "vitamin", "calcium",
    "omega", "collagen", "spa", "massage", "yoga", "gym",
    "fitness", "cardio", "pilates",
    # Transport
    "taxi", "bus", "metro", "uber", "xe", "suv", "sedan",
    # Vietnamese brands / organizations (no-diacritics form)
    "vietcombank", "vietinbank", "bidv", "agribank", "techcombank",
    "vietjet", "vietnamairlines", "bamboo", "viettel", "mobifone",
    "vinaphone", "fpt", "vnpt", "vng",
    # Vietnamese places (no-diacritics form)
    "hanoi", "saigon", "hcm", "hcmc", "danang", "hue", "nhatrang",
    "cantho", "haiphong", "dalat", "vungtau", "phuquoc",
    "vietnam", "vietnamese",
}


class PromptValidator:
    """Validates and filters generated Vietnamese red-teaming prompts."""

    def __init__(
        self,
        min_length: int = MIN_PROMPT_LENGTH,
        max_length: int = MAX_PROMPT_LENGTH,
        min_vn_ratio: float = 0.6,
    ):
        """
        Args:
            min_length: Minimum characters for a valid prompt.
            max_length: Maximum characters for a valid prompt.
            min_vn_ratio: Minimum ratio of Vietnamese chars to total chars.
        """
        self.min_length = min_length
        self.max_length = max_length
        self.min_vn_ratio = min_vn_ratio

    def _vn_char_ratio(self, text: str) -> float:
        """Compute ratio of Vietnamese/Latin characters to total non-space chars."""
        non_space = text.replace(" ", "")
        if not non_space:
            return 0.0
        vn_chars = len(VN_CHAR_PATTERN.findall(non_space))
        return vn_chars / len(non_space)

    @staticmethod
    def _count_foreign_words(text: str) -> int:
        """
        Count genuinely foreign/English words, excluding Vietnamese loanwords.

        Words in VN_LOANWORD_WHITELIST are treated as native Vietnamese usage.
        Only words 3+ characters long are considered.
        """
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return sum(1 for w in words if w not in VN_LOANWORD_WHITELIST)

    def validate_single(
        self,
        prompt: str,
        cat_code: str = None,
        type_name: str = None,
    ) -> Tuple[bool, str]:
        """
        Validate a single generated Vietnamese prompt.

        Returns:
            Tuple of (is_valid, reason).
        """
        if not prompt or not isinstance(prompt, str):
            return False, "Empty or non-string prompt"

        prompt_stripped = prompt.strip()

        # Length checks
        if len(prompt_stripped) < self.min_length:
            return False, f"Too short ({len(prompt_stripped)} < {self.min_length})"

        if len(prompt_stripped) > self.max_length:
            return False, f"Too long ({len(prompt_stripped)} > {self.max_length})"

        # Vietnamese character ratio
        vn_ratio = self._vn_char_ratio(prompt_stripped)
        if vn_ratio < self.min_vn_ratio:
            return False, (
                f"Insufficient Vietnamese characters "
                f"(ratio {vn_ratio:.2f} < {self.min_vn_ratio})"
            )

        # Check for excessive English, excluding Vietnamese loanwords
        foreign_count = self._count_foreign_words(prompt_stripped)
        # Allow proportional threshold: ~10% of word count or at most 8 words
        total_words = len(prompt_stripped.split())
        max_allowed = max(5, int(total_words * 0.12))
        if foreign_count > max_allowed:
            return False, (
                f"Too many foreign words ({foreign_count}) "
                f"vs {total_words} total words (max {max_allowed} allowed)"
            )

        return True, "OK"

    def validate_batch(
        self,
        prompts: List[str],
        cat_codes: List[str] = None,
        type_names: List[str] = None,
    ) -> List[Dict]:
        """
        Validate a batch of prompts, returning validation results.

        Returns:
            List of dicts with 'index', 'prompt', 'valid', 'reason'.
        """
        n = len(prompts)
        if cat_codes is None:
            cat_codes = [None] * n
        if type_names is None:
            type_names = [None] * n

        results = []
        for i, (prompt, cat, tp) in enumerate(zip(prompts, cat_codes, type_names)):
            valid, reason = self.validate_single(prompt, cat, tp)
            results.append({
                "index": i,
                "prompt": prompt,
                "category": cat,
                "type": tp,
                "valid": valid,
                "reason": reason,
            })
        return results

    def filter_valid(
        self,
        prompts: List[str],
        cat_codes: List[str] = None,
        type_names: List[str] = None,
    ) -> Tuple[List[str], List[str], List[str], Dict]:
        """
        Filter prompts, returning only valid ones with their metadata.

        Returns:
            Tuple of (valid_prompts, valid_cats, valid_types, stats_dict).
        """
        results = self.validate_batch(prompts, cat_codes, type_names)

        valid_prompts = []
        valid_cats = []
        valid_types = []

        stats = {
            "total": len(results),
            "valid": 0,
            "invalid": 0,
            "reasons": {},
        }

        for r in results:
            if r["valid"]:
                valid_prompts.append(r["prompt"])
                valid_cats.append(r["category"])
                valid_types.append(r["type"])
                stats["valid"] += 1
            else:
                stats["invalid"] += 1
                reason = r["reason"]
                stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1

        logger.info(
            f"Validation: {stats['valid']}/{stats['total']} passed "
            f"({100*stats['valid']/max(stats['total'],1):.1f}%)"
        )

        return valid_prompts, valid_cats, valid_types, stats

    @staticmethod
    def deduplicate(
        prompts: List[str],
        cat_codes: List[str] = None,
        type_names: List[str] = None,
    ) -> Tuple[List[str], List[str], List[str], int]:
        """
        Remove duplicate prompts (normalized comparison).

        Returns:
            Tuple of (unique_prompts, unique_cats, unique_types, removed_count).
        """
        seen = set()
        unique_prompts = []
        unique_cats = []
        unique_types = []
        removed = 0

        for i, prompt in enumerate(prompts):
            normalized = " ".join(prompt.strip().lower().split())
            if normalized in seen:
                removed += 1
                continue
            seen.add(normalized)
            unique_prompts.append(prompt)
            if cat_codes:
                unique_cats.append(cat_codes[i])
            if type_names:
                unique_types.append(type_names[i])

        logger.info(f"Deduplication: removed {removed} duplicates")
        return unique_prompts, unique_cats, unique_types, removed

    @staticmethod
    def validate_json_output(raw_json: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Validate a JSON response from the generation model.

        Returns:
            Tuple of (is_valid, parsed_dict_or_None, error_message).
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return False, None, f"JSON decode error: {e}"

        if "vietnamese_prompt" not in data:
            return False, None, "Missing 'vietnamese_prompt' field"

        prompt = data.get("vietnamese_prompt", "")
        if not prompt or not isinstance(prompt, str):
            return False, None, "'vietnamese_prompt' is empty or not a string"

        return True, data, "OK"
