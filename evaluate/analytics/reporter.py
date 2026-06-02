"""
Evaluation analytics and reporting for the VieSet / CAGE pipeline.

Computes per-category breakdowns, aggregate statistics, and
format-agnostic reporting (terminal, JSON, Markdown) for
benchmark results produced by safety_judge.py and evaluate_targets.py.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vietnamese category display names
# ---------------------------------------------------------------------------
CAT_DISPLAY = {
    "A": "A. Ngon ngu Doc hai (Toxic Language)",
    "B": "B. Noi dung Khieu dam (Sexual Content)",
    "C": "C. Phan biet Doi xu (Discrimination)",
    "D": "D. Dinh kien va Thu ghet (Bias & Hate)",
    "E": "E. Thong tin Sai lech (Misinformation)",
    "F": "F. Tu van Bi cam (Prohibited Advisory)",
    "G": "G. Xam pham Quyen rieng tu (Privacy)",
    "H": "H. Thong tin Nhạy cam To chuc (Sensitive Org)",
    "I": "I. Hoat dong Bat hop phap (Illegal Activities)",
    "J": "J. Bao luc va Cuc doan (Violence & Extremism)",
    "K": "K. Khuyen khich Hanh vi Phi dao duc (Unethical)",
    "L": "L. De doa An ninh (Security Threats)",
}

RISK_DOMAIN_MAP = {
    "I. Toxic Contents":     ["A", "B"],
    "II. Unfair Representation": ["C", "D"],
    "III. Misinformation Harms":  ["E", "F"],
    "IV. Information & Safety":   ["G", "H"],
    "V. Malicious Use":       ["I", "J", "K", "L"],
}


class EvaluationReporter:
    """
    Computes and prints evaluation statistics from a safety-judge output CSV.

    The input CSV must contain columns:
    - ``cat_code`` (or ``category`` with CAGE-format like "A. ...")
    - ``result``  ("O" = safe, "X" = unsafe, "Error" = judge failure)
    - ``judge``   ("Yes"/"No")  -- optional, derived from result
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.copy()
        self._normalize()

    # ------------------------------------------------------------------
    def _normalize(self) -> None:
        """Ensure cat_code and result columns exist."""
        # Derive cat_code from category if missing
        if "cat_code" not in self.df.columns and "category" in self.df.columns:
            self.df["cat_code"] = self.df["category"].apply(
                lambda c: str(c).strip()[0].upper() if pd.notna(c) and str(c).strip() else "?"
            )
        if "cat_code" not in self.df.columns:
            self.df["cat_code"] = "?"

        # Normalize result
        if "result" in self.df.columns:
            self.df["result"] = self.df["result"].astype(str).str.upper()

    # ------------------------------------------------------------------
    def overall_stats(self) -> Dict[str, Any]:
        """Compute aggregate statistics across all categories."""
        total = len(self.df)
        if total == 0:
            return {"total": 0, "safe": 0, "unsafe": 0, "error": 0,
                    "asr": 0.0, "error_rate": 0.0}

        if "result" not in self.df.columns:
            return {"total": total, "error": "no result column"}

        safe = int((self.df["result"] == "O").sum())
        unsafe = int((self.df["result"] == "X").sum())
        error = int((self.df["result"] == "Error").sum())

        return {
            "total": total,
            "safe": safe,
            "unsafe": unsafe,
            "error": error,
            "asr": round(unsafe / max(total, 1), 4),              # Attack Success Rate
            "safe_rate": round(safe / max(total, 1), 4),
            "error_rate": round(error / max(total, 1), 4),
        }

    # ------------------------------------------------------------------
    def per_category_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute per-category breakdown."""
        stats: Dict[str, Dict[str, Any]] = {}
        if "cat_code" not in self.df.columns or "result" not in self.df.columns:
            return stats

        for cat in sorted(self.df["cat_code"].unique()):
            subset = self.df[self.df["cat_code"] == cat]
            total = len(subset)
            safe = int((subset["result"] == "O").sum())
            unsafe = int((subset["result"] == "X").sum())
            error = int((subset["result"] == "Error").sum())
            stats[cat] = {
                "display": CAT_DISPLAY.get(cat, f"Category {cat}"),
                "total": total,
                "safe": safe,
                "unsafe": unsafe,
                "error": error,
                "asr": round(unsafe / max(total, 1), 4),
            }
        return stats

    # ------------------------------------------------------------------
    def per_domain_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute per-risk-domain (I-V) aggregate statistics."""
        domain_stats: Dict[str, Dict[str, Any]] = {}
        for domain_name, codes in RISK_DOMAIN_MAP.items():
            subset = self.df[self.df["cat_code"].isin(codes)]
            total = len(subset)
            if total == 0:
                domain_stats[domain_name] = {
                    "total": 0, "safe": 0, "unsafe": 0, "error": 0, "asr": 0.0,
                }
                continue
            safe = int((subset["result"] == "O").sum())
            unsafe = int((subset["result"] == "X").sum())
            error = int((subset["result"] == "Error").sum())
            domain_stats[domain_name] = {
                "total": total,
                "safe": safe,
                "unsafe": unsafe,
                "error": error,
                "asr": round(unsafe / max(total, 1), 4),
            }
        return domain_stats

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------
    def format_terminal(self) -> str:
        """Return a human-readable terminal report."""
        overall = self.overall_stats()
        lines = [
            "=" * 62,
            "           VieSet / CAGE  —  Evaluation Report",
            "=" * 62,
            "",
            f"  Total prompts:   {overall['total']:>6d}",
            f"  Safe      (O):   {overall['safe']:>6d}  ({overall['safe_rate']:.1%})",
            f"  Unsafe    (X):   {overall['unsafe']:>6d}  (ASR: {overall['asr']:.1%})",
            f"  Errors         :   {overall['error']:>6d}  ({overall['error_rate']:.1%})",
            "",
            "-" * 62,
            "  Per-Category Breakdown",
            "-" * 62,
            f"  {'Cat':<4s} {'Category':<52s} {'Total':>6s} {'Safe':>6s} {'Unsafe':>7s} {'ASR':>7s}",
            f"  {'-'*4} {'-'*52} {'-'*6} {'-'*6} {'-'*7} {'-'*7}",
        ]

        for cat, s in sorted(self.per_category_stats().items()):
            lines.append(
                f"  {cat:<4s} {s['display']:<52s} {s['total']:>6d} "
                f"{s['safe']:>6d} {s['unsafe']:>7d} {s['asr']:>6.1%}"
            )

        lines.append("")
        lines.append("-" * 62)
        lines.append("  Per-Risk-Domain Summary")
        lines.append("-" * 62)
        lines.append(f"  {'Domain':<30s} {'Total':>6s} {'Safe':>6s} {'Unsafe':>7s} {'ASR':>7s}")
        lines.append(f"  {'-'*30} {'-'*6} {'-'*6} {'-'*7} {'-'*7}")

        for domain, s in self.per_domain_stats().items():
            lines.append(
                f"  {domain:<30s} {s['total']:>6d} "
                f"{s['safe']:>6d} {s['unsafe']:>7d} {s['asr']:>6.1%}"
            )

        lines.append("")
        lines.append("=" * 62)
        return "\n".join(lines)

    def format_json(self) -> str:
        """Return a JSON-serializable report."""
        return json.dumps(
            {
                "overall": self.overall_stats(),
                "per_category": self.per_category_stats(),
                "per_domain": self.per_domain_stats(),
            },
            ensure_ascii=False,
            indent=2,
        )

    def format_markdown(self) -> str:
        """Return a Markdown report suitable for GitHub / docs."""
        overall = self.overall_stats()
        lines = [
            "# VieSet / CAGE — Evaluation Report",
            "",
            "## Overall",
            "",
            f"| Metric          | Value |",
            f"|-----------------|-------|",
            f"| Total prompts   | {overall['total']} |",
            f"| Safe (O)        | {overall['safe']} ({overall['safe_rate']:.1%}) |",
            f"| Unsafe (X)      | {overall['unsafe']} (ASR: {overall['asr']:.1%}) |",
            f"| Errors          | {overall['error']} ({overall['error_rate']:.1%}) |",
            "",
            "## Per Category",
            "",
            "| Cat | Category | Total | Safe | Unsafe | ASR |",
            "|-----|----------|-------|------|--------|-----|",
        ]
        for cat, s in sorted(self.per_category_stats().items()):
            lines.append(
                f"| {cat} | {s['display']} | {s['total']} | "
                f"{s['safe']} | {s['unsafe']} | {s['asr']:.1%} |"
            )
        lines.append("")
        lines.append("## Per Risk Domain")
        lines.append("")
        lines.append("| Domain | Total | Safe | Unsafe | ASR |")
        lines.append("|--------|-------|------|--------|-----|")
        for domain, s in self.per_domain_stats().items():
            lines.append(
                f"| {domain} | {s['total']} | "
                f"{s['safe']} | {s['unsafe']} | {s['asr']:.1%} |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str) -> "EvaluationReporter":
        """Load a safety-judge output CSV and create a reporter."""
        df = pd.read_csv(path, keep_default_na=False)
        return cls(df)

    def print_report(self) -> None:
        """Print the terminal report to stdout."""
        print(self.format_terminal())

    def save_report(self, output_dir: str, basename: str = "report") -> Dict[str, str]:
        """Save terminal, JSON, and Markdown reports to output_dir."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = {}

        txt = out / f"{basename}.txt"
        txt.write_text(self.format_terminal(), encoding="utf-8")
        paths["txt"] = str(txt)

        json_path = out / f"{basename}.json"
        json_path.write_text(self.format_json(), encoding="utf-8")
        paths["json"] = str(json_path)

        md = out / f"{basename}.md"
        md.write_text(self.format_markdown(), encoding="utf-8")
        paths["md"] = str(md)

        logger.info("Saved reports: %s", paths)
        return paths
