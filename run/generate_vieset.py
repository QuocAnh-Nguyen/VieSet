"""
VieSet: Vietnamese Culturally Adaptive Red-Teaming Benchmark Generator.

Main entry point for the CAGE generation pipeline targeting the Vietnamese
language and cultural context. Implements the full 3-stage pipeline:

  Stage 1: Seed Collection & Taxonomy Mapping
  Stage 2: Refine-with-Slot (Semantic Mold)
  Stage 3: Translate-with-Context (Content Localization)

Output is a CSV file in data/ compatible with run/safety_judge.py.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd

# Add project root to path (mirroring safety_judge.py pattern)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from generate.base.generator_base import GenerationClient
from generate.template.molds import (
    CAT_CODE_TO_VN,
    RISK_DOMAINS,
    get_all_required_slots,
    get_all_optional_slots,
    get_slots_for_category,
)
from generate.template.refiner import SemanticRefiner
from generate.template.vn.translator import VietnameseTranslator
from generate.template.vn.content_repo import get_content_for_category
from generate.utils.validator import PromptValidator

# ---------------------------------------------------------------------------
# Logging setup -- mirrors evaluate/utils/logger.py conventions
# ---------------------------------------------------------------------------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "generate_vieset.log")),
    ],
)
logger = logging.getLogger("generate_vieset")

# Default data paths
DEFAULT_SEED_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "sample_data.csv"
)
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ===================================================================
# STAGE 1: Seed Collection (taxonomy-based from input CSV)
# ===================================================================

def collect_seeds(
    seed_path: str,
    prompt_col: str = "seed",
    domain_col: str = "domain",
    category_col: str = "category",
    response_col: str = "response",
) -> pd.DataFrame:
    """
    Load seed prompts from input CSV and map to CAGE taxonomy.

    Mirrors the structure expected by safety_judge.py.
    Returns DataFrame with columns: domain, category, seed, response.
    """
    if not os.path.exists(seed_path):
        raise FileNotFoundError(f"Seed file not found: {seed_path}")

    logger.info(f"Loading seeds from {seed_path} ...")
    df = pd.read_csv(seed_path, keep_default_na=False)

    # Ensure required columns
    for col in [prompt_col, category_col]:
        if col not in df.columns:
            raise ValueError(f"Required column '{col}' not found in input CSV")

    # Normalize column names to match the evaluate pipeline convention
    df = df.rename(
        columns={
            prompt_col: "seed",
            category_col: "category",
        }
    )
    if domain_col in df.columns:
        df = df.rename(columns={domain_col: "domain"})
    if response_col in df.columns:
        df = df.rename(columns={response_col: "response"})

    # Extract single-letter category code from e.g. "A. Ngôn ngữ Độc hại"
    df["cat_code"] = df["category"].apply(
        lambda c: c.strip()[0].upper() if c and len(c.strip()) > 0 else "A"
    )

    logger.info(f"Loaded {len(df)} seed prompts across {df['cat_code'].nunique()} categories")
    return df


# ===================================================================
# STAGE 2: Refine-with-Slot (Semantic Mold creation)
# ===================================================================

def refine_seeds(
    client: GenerationClient,
    seeds_df: pd.DataFrame,
    max_samples_per_cat: int = 20,
) -> List[Dict]:
    """
    Convert English seed prompts into slot-tagged semantic molds.

    Returns list of dicts with keys: seed, cat_code, refined_mold, preserved_intent.
    """
    refiner = SemanticRefiner()
    results = []
    total = 0

    for cat_code, group in seeds_df.groupby("cat_code"):
        # Limit per category for efficiency
        samples = group.head(max_samples_per_cat)
        logger.info(
            f"Refining {len(samples)} seeds for category "
            f"{CAT_CODE_TO_VN.get(cat_code, cat_code)} ..."
        )

        for _, row in samples.iterrows():
            seed = row["seed"]
            prompt = refiner.build_refiner_prompt(seed, cat_code)

            try:
                raw = client.generate_json(
                    input_text=prompt,
                    system_prompt=refiner.system_prompt,
                    temperature=0.5,
                    max_tokens=2048,
                )
                parsed = json.loads(raw)
                results.append({
                    "seed": seed,
                    "cat_code": cat_code,
                    "category": CAT_CODE_TO_VN.get(cat_code, cat_code),
                    "refined_mold": parsed.get("refined_prompt", ""),
                    "filled_slots": parsed.get("filled_slots", {}),
                    "preserved_intent": parsed.get("preserved_intent", ""),
                })
                total += 1
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Failed to parse refinement JSON for cat {cat_code}: {e}"
                )
                continue

            # Rate limiting
            time.sleep(0.2)

    logger.info(f"Stage 2 complete: {total} refined molds produced")
    return results


# ===================================================================
# Helper: Format content context for the translator
# ===================================================================

def _format_content_context(cat_code: str) -> str:
    """Format Vietnamese cultural content from the repository for a prompt."""
    content = get_content_for_category(cat_code)
    if not content:
        return ""

    lines = []
    for key, items in content.items():
        if isinstance(items, list) and items:
            lines.append(f"- {key}: {', '.join(items[:5])}" +
                         (f" +{len(items)-5} more" if len(items) > 5 else ""))
    return "\n".join(lines)


# ===================================================================
# STAGE 3: Translate-with-Context (Content Localization)
# ===================================================================

def localize_molds(
    client: GenerationClient,
    refined_molds: List[Dict],
) -> List[Dict]:
    """
    Instantiate semantic molds with Vietnamese cultural content.

    Returns list of dicts with keys:
        seed, cat_code, vietnamese_prompt, filled_slots_vn, cultural_anchors.
    """
    translator = VietnameseTranslator()
    validator = PromptValidator()
    results = []
    total = 0
    failed = 0

    for item in refined_molds:
        cat_code = item["cat_code"]
        refined_mold = item["refined_mold"]
        if not refined_mold:
            continue

        content_ctx = _format_content_context(cat_code)
        prompt = translator.build_translator_prompt(
            refined_mold=refined_mold,
            cat_code=cat_code,
            content_context=content_ctx,
        )

        try:
            raw = client.generate_json(
                input_text=prompt,
                system_prompt=translator.system_prompt,
                temperature=0.8,  # Higher temperature for diversity
                max_tokens=2048,
            )

            is_valid, parsed, err = validator.validate_json_output(raw)
            if not is_valid:
                logger.warning(
                    f"Invalid JSON from translator for cat {cat_code}: {err}"
                )
                failed += 1
                continue

            vn_prompt = parsed.get("vietnamese_prompt", "")

            # Additional content validation
            valid, reason = validator.validate_single(vn_prompt, cat_code)
            if not valid:
                logger.warning(
                    f"Content validation failed for cat {cat_code}: {reason}"
                )
                failed += 1
                continue

            results.append({
                "seed": item["seed"],
                "cat_code": cat_code,
                "category": item["category"],
                "refined_mold": refined_mold,
                "vietnamese_prompt": vn_prompt,
                "filled_slots_vn": parsed.get("filled_slots_vn", {}),
                "cultural_anchors": parsed.get("cultural_anchors", []),
            })
            total += 1

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for cat {cat_code}: {e}")
            failed += 1
            continue

        except Exception as e:
            logger.error(f"Unexpected error for cat {cat_code}: {e}")
            failed += 1
            continue

        # Rate limiting
        time.sleep(0.3)

    logger.info(
        f"Stage 3 complete: {total} localized prompts ({failed} failed)"
    )
    return results


# ===================================================================
# Final Output: Format for compatibility with safety_judge.py
# ===================================================================

def export_dataset(
    localized: List[Dict],
    output_dir: str,
    output_filename: str,
    include_refined: bool = False,
) -> str:
    """
    Export the generated dataset to CSV format compatible with safety_judge.py.

    CSV columns: domain, category, seed (prompt), response, gt
    """
    validator = PromptValidator()

    # Map cat_code to domain
    cat_to_domain = {}
    for domain, codes in RISK_DOMAINS.items():
        for code in codes:
            cat_to_domain[code] = domain

    rows = []
    for item in localized:
        vn_prompt = item["vietnamese_prompt"]
        valid, _ = validator.validate_single(vn_prompt, item["cat_code"])
        if not valid:
            continue

        row = {
            "domain": cat_to_domain.get(item["cat_code"], ""),
            "category": item["category"],
            "seed": vn_prompt,  # The Vietnamese prompt goes in 'seed' column
            "response": "",      # To be filled by target LLM during evaluation
            "gt": "TRUE",        # Ground truth: prompt IS harmful (X)
        }
        if include_refined:
            row["refined_mold"] = item.get("refined_mold", "")
        rows.append(row)

    df = pd.DataFrame(rows)

    # Deduplicate
    before = len(df)
    df = df.drop_duplicates(subset=["seed"])
    after = len(df)
    if before != after:
        logger.info(f"Deduplication: {before} -> {after} ({before - after} removed)")

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, output_filename)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    logger.info(f"Dataset exported to {output_path}: {len(df)} prompts")
    logger.info(f"  Categories: {df['category'].value_counts().to_dict()}")

    # Print cost summary
    return output_path


# ===================================================================
# Main Pipeline Orchestrator
# ===================================================================

def run_pipeline(
    seed_path: str,
    output_dir: str,
    output_filename: str,
    model: str = "gpt-4.1",
    api_key: str = None,
    max_per_category: int = 20,
    skip_refine: bool = False,
    seed_prompt_col: str = "seed",
    seed_category_col: str = "category",
    seed_domain_col: str = "domain",
    seed_response_col: str = "response",
    include_refined: bool = False,
) -> Tuple[str, Dict]:
    """
    Run the full CAGE generation pipeline for Vietnamese.

    Returns:
        Tuple of (output_path, stats_dict).
    """
    stats = {}

    # ---- Initialize generation client ----
    logger.info(f"Initializing generation model: {model}")
    client = GenerationClient(model=model, api_key=api_key)

    # ---- Stage 1: Collect seeds ----
    logger.info("=" * 50)
    logger.info("STAGE 1: Seed Collection")
    logger.info("=" * 50)
    seeds_df = collect_seeds(
        seed_path,
        prompt_col=seed_prompt_col,
        category_col=seed_category_col,
        domain_col=seed_domain_col,
        response_col=seed_response_col,
    )
    stats["total_seeds"] = len(seeds_df)
    stats["categories"] = seeds_df["cat_code"].nunique()

    if skip_refine:
        logger.info("Skipping Stage 2 (refine), using seeds directly as molds")
        refined_molds = []
        for _, row in seeds_df.head(max_per_category * 12).iterrows():
            refined_molds.append({
                "seed": row["seed"],
                "cat_code": row["cat_code"],
                "category": CAT_CODE_TO_VN.get(row["cat_code"], row["category"]),
                "refined_mold": row["seed"],  # Use seed directly
                "filled_slots": {},
                "preserved_intent": "",
            })
    else:
        # ---- Stage 2: Refine-with-Slot ----
        logger.info("=" * 50)
        logger.info("STAGE 2: Refine-with-Slot")
        logger.info("=" * 50)
        refined_molds = refine_seeds(
            client, seeds_df, max_per_category
        )
        stats["refined_molds"] = len(refined_molds)

    # ---- Stage 3: Translate-with-Context ----
    logger.info("=" * 50)
    logger.info("STAGE 3: Translate-with-Context")
    logger.info("=" * 50)
    localized = localize_molds(client, refined_molds)
    stats["localized_prompts"] = len(localized)

    # ---- Export ----
    logger.info("=" * 50)
    logger.info("EXPORT: Saving Final Dataset")
    logger.info("=" * 50)
    output_path = export_dataset(
        localized, output_dir, output_filename, include_refined
    )

    # ---- Usage summary ----
    stats["total_tokens"] = client.total_tokens
    stats["total_cost_usd"] = round(client.total_cost, 4)
    logger.info(f"Total tokens: {client.total_tokens}")
    logger.info(f"Estimated cost: ${client.total_cost:.4f}")

    return output_path, stats


# ===================================================================
# CLI Entry Point
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="VieSet: Generate Vietnamese Culturally Adaptive Red-Teaming Dataset"
    )

    # Input/Output
    parser.add_argument(
        "--input", "-i",
        default=DEFAULT_SEED_PATH,
        help=f"Input seed CSV file path (default: {DEFAULT_SEED_PATH})",
    )
    parser.add_argument(
        "--outdir", "-d",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--outfile", "-o",
        default="vieset_benchmark.csv",
        help="Output CSV filename (default: vieset_benchmark.csv)",
    )

    # Column mapping (mirrors safety_judge.py)
    parser.add_argument(
        "--prompt_col", "-pc",
        default="seed",
        help="Column name for seed prompts (default: seed)",
    )
    parser.add_argument(
        "--category_col", "-cc",
        default="category",
        help="Column name for categories (default: category)",
    )
    parser.add_argument(
        "--domain_col", "-dc",
        default="domain",
        help="Column name for domains (default: domain)",
    )
    parser.add_argument(
        "--response_col", "-rc",
        default="response",
        help="Column name for responses (default: response)",
    )

    # Generation parameters
    parser.add_argument(
        "--model", "-m",
        default="gpt-4.1",
        help="Generator model (default: gpt-4.1)",
    )
    parser.add_argument(
        "--api_key", "-a",
        default=None,
        help="OpenAI API key (default: from OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--max_per_category",
        type=int,
        default=20,
        help="Max seeds to generate per category (default: 20)",
    )

    # Flags
    parser.add_argument(
        "--skip_refine",
        action="store_true",
        help="Skip Stage 2 refinement (use seeds directly as molds)",
    )
    parser.add_argument(
        "--include_refined",
        action="store_true",
        help="Include refined mold column in output CSV",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Load seeds and print stats without generating",
    )

    args = parser.parse_args()

    if args.dry_run:
        seeds_df = collect_seeds(
            args.input,
            prompt_col=args.prompt_col,
            category_col=args.category_col,
            domain_col=args.domain_col,
            response_col=args.response_col,
        )
        print(f"\nSeed summary:")
        print(f"  Total seeds: {len(seeds_df)}")
        print(f"  Categories:  {seeds_df['cat_code'].nunique()}")
        print(f"  Per category:\n{seeds_df['cat_code'].value_counts().to_string()}")
        return

    output_path, stats = run_pipeline(
        seed_path=args.input,
        output_dir=args.outdir,
        output_filename=args.outfile,
        model=args.model,
        api_key=args.api_key,
        max_per_category=args.max_per_category,
        skip_refine=args.skip_refine,
        seed_prompt_col=args.prompt_col,
        seed_category_col=args.category_col,
        seed_domain_col=args.domain_col,
        seed_response_col=args.response_col,
        include_refined=args.include_refined,
    )

    print(f"\n=== VieSet Generation Complete ===")
    print(f"Output:          {output_path}")
    print(f"Total prompts:   {stats.get('localized_prompts', 0)}")
    print(f"Total tokens:    {stats.get('total_tokens', 0)}")
    print(f"Estimated cost:  ${stats.get('total_cost_usd', 0):.4f}")
    print(f"\nTo evaluate: python run/safety_judge.py -i {output_path} "
          f"-d results -o result_vn.csv -m prompt -l vn -a YOUR_API_KEY")


if __name__ == "__main__":
    main()
