"""
VieSet: Vietnamese Culturally Adaptive Red-Teaming Benchmark Generator.

Main entry point for the CAGE generation pipeline targeting the Vietnamese
language and cultural context. Implements the full 3-stage pipeline:

  Stage 1: Seed Collection & Taxonomy Mapping
  Stage 2: Refine-with-Slot (Semantic Mold)
  Stage 3: Translate-with-Context (Content Localization)

Output is a CSV file in data/ compatible with run/safety_judge.py.

Phase 1 Refactor:
- Uses ``LLMClient`` (litellm-backed) with async generation + retry.
- Uses ``AsyncPipelineEngine`` for concurrent stage 2 & 3 execution.
- Uses ``CheckpointManager`` for incremental fault-tolerant saves.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

# Add project root to path (mirroring safety_judge.py pattern)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from generate.base.llm_client import LLMClient, strip_markdown_wrapper, parse_json
from generate.base.async_engine import AsyncPipelineEngine, CheckpointManager
from generate.template.molds import (
    CAT_CODE_TO_VN,
    RISK_DOMAINS,
    get_all_required_slots,
    get_all_optional_slots,
    get_slots_for_category,
)
from generate.template.refiner import SemanticRefiner
from generate.template.vn.translator import VietnameseTranslator
from generate.template.vn.content_repo import (
    get_content_for_category, build_context_string, inject_dynamic_content
)
from generate.auto_labeler import AutoLabeler
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
DEFAULT_CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "..", "checkpoints")

# ===================================================================
# STAGE 1: Seed Collection (taxonomy-based from input CSV)
# ===================================================================


async def collect_seeds(
    seed_path: str,
    prompt_col: str = "seed",
    domain_col: str = "domain",
    category_col: str = "category",
    response_col: str = "response",
    auto_labeler: "Optional[AutoLabeler]" = None,
) -> pd.DataFrame:
    """
    Load seed prompts from input CSV and map to CAGE taxonomy.

    Uses LLM-based AutoLabeler (Phase 2) when available to map
    arbitrary source categories to CAGE codes A-L. Falls back to
    keyword heuristics if no labeler is provided.

    Mirrors the structure expected by safety_judge.py.
    Returns DataFrame with columns: domain, category, seed, response, cat_code.
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

    # Phase 2: LLM-based auto-labeling (replaces c[0].upper() string slicing)
    unique_cats = df["category"].unique().tolist()
    cat_map: Dict[str, str] = {}
    type_map: Dict[str, str] = {}

    if auto_labeler is not None:
        logger.info("Auto-labeling %d unique categories via LLM/Heuristic...", len(unique_cats))
        for cat_name in unique_cats:
            code, type_name, rationale = await auto_labeler.map_category(str(cat_name))
            cat_map[str(cat_name)] = code
            type_map[str(cat_name)] = type_name
            logger.info("  %s -> %s / %s (%s)", cat_name, code, type_name or "-", rationale)
    else:
        # Pure heuristic fallback (no async needed)
        logger.info("No AutoLabeler provided, using heuristic mapping...")
        for cat_name in unique_cats:
            code, rationale = AutoLabeler.heuristic_map(str(cat_name))
            cat_map[str(cat_name)] = code
            logger.info("  %s -> %s (%s)", cat_name, code, rationale)

    df["cat_code"] = df["category"].map(cat_map).fillna("A")
    if type_map:
        df["type_name"] = df["category"].map(type_map).fillna("")

    logger.info(
        f"Loaded {len(df)} seed prompts across {df['cat_code'].nunique()} categories"
    )
    return df


# ===================================================================
# STAGE 2: Refine-with-Slot (Semantic Mold creation)  --  ASYNC
# ===================================================================


async def refine_seeds_async(
    client: LLMClient,
    engine: AsyncPipelineEngine,
    seeds_df: pd.DataFrame,
    max_samples_per_cat: int = 20,
) -> List[Dict]:
    """
    Convert English seed prompts into slot-tagged semantic molds (async).

    Returns list of dicts with keys: seed, cat_code, refined_mold, preserved_intent.
    """
    refiner = SemanticRefiner()

    # Build the list of (cat_code, row_index, seed, task_fn) entries
    task_specs: List[Dict] = []
    for cat_code, group in seeds_df.groupby("cat_code"):
        samples = group.head(max_samples_per_cat)
        logger.info(
            f"Preparing {len(samples)} seeds for category "
            f"{CAT_CODE_TO_VN.get(cat_code, cat_code)} ..."
        )
        for row_idx, row in samples.iterrows():
            seed = row["seed"]
            type_name = row.get("type_name", "") if "type_name" in row.index else ""
            prompt = refiner.build_refiner_prompt(seed, cat_code, type_name)

            # Capture by-value in closure via default arg
            async def _task(
                _seed=seed,
                _cat=cat_code,
                _type=type_name,
                _prompt=prompt,
                _seed_idx=row_idx,
            ) -> dict:
                raw = await client.agenerate_json(
                    input_text=_prompt,
                    system_prompt=refiner.system_prompt,
                    temperature=0.3,
                )
                ok, parsed, err = parse_json(raw)
                if not ok:
                    logger.warning(
                        f"Refine JSON parse failed for seed: {_seed[:60]}... | {err}"
                    )
                    return {
                        "seed": _seed,
                        "cat_code": _cat,
                        "type_name": _type,
                        "seed_index": _seed_idx,
                        "refined_mold": _seed,  # fallback: use original
                        "preserved_intent": "",
                        "parse_error": err,
                    }
                return {
                    "seed": _seed,
                    "cat_code": _cat,
                    "type_name": _type,
                    "seed_index": _seed_idx,
                    "refined_mold": parsed.get("refined_prompt", _seed),
                    "preserved_intent": parsed.get("preserved_intent", ""),
                }

            task_specs.append(_task)

    # Run all tasks concurrently
    results_raw = await engine.run(tasks=task_specs, stage="refine")

    # Gather successful results
    results: List[Dict] = []
    for idx, result, error in results_raw:
        if error is not None:
            logger.error(f"Refine task {idx} failed: {error}")
        elif result is not None:
            results.append(result)

    logger.info(f"Refine complete: {len(results)} molds created")
    return results


# ===================================================================
# STAGE 3: Translate-with-Context (Content Localization)  -- ASYNC
# ===================================================================


async def localize_molds_async(
    client: LLMClient,
    engine: AsyncPipelineEngine,
    refined_molds: List[Dict],
) -> List[Dict]:
    """
    Instantiate semantic molds with Vietnamese cultural content (async).

    Returns list of dicts with full prompt metadata.
    """
    translator = VietnameseTranslator()

    def _build_tasks():
        for mold_entry in refined_molds:
            mold_text = mold_entry.get("refined_mold", "")
            cat_code = mold_entry.get("cat_code", "A")
            # Phase 2: mixed static + dynamic content via build_context_string
            content_context = build_context_string(cat_code)
            if not content_context:
                # Fall back to full static dict if no dynamic content available
                content = get_content_for_category(cat_code)
                content_context = json.dumps(content, ensure_ascii=False, indent=2)
            prompt = translator.build_translator_prompt(
                mold_text, cat_code, content_context=content_context
            )

            async def _task(
                _mold=mold_text,
                _cat=cat_code,
                _prompt=prompt,
                _entry=mold_entry,
            ) -> dict:
                raw = await client.agenerate_json(
                    input_text=_prompt,
                    system_prompt=translator.system_prompt,
                    temperature=0.7,
                )
                ok, parsed, err = parse_json(raw)
                if not ok:
                    logger.warning(
                        f"Translate JSON parse failed for mold: {_mold[:60]}... | {err}"
                    )
                    return {
                        **_entry,
                        "vietnamese_prompt": _mold,
                        "filled_slots_vn": {},
                        "cultural_anchors": [],
                        "parse_error": err,
                    }
                return {
                    **_entry,
                    "vietnamese_prompt": parsed.get("vietnamese_prompt", _mold),
                    "filled_slots_vn": parsed.get("filled_slots_vn", {}),
                    "cultural_anchors": parsed.get("cultural_anchors", []),
                }

            yield _task

    tasks = list(_build_tasks())

    if not tasks:
        logger.warning("No molds to localize")
        return []

    results_raw = await engine.run(tasks=tasks, stage="localize")

    results: List[Dict] = []
    for idx, result, error in results_raw:
        if error is not None:
            logger.error(f"Localize task {idx} failed: {error}")
        elif result is not None:
            results.append(result)

    logger.info(f"Localize complete: {len(results)} prompts generated")
    return results


# ===================================================================
# STAGE 2 (SYNC FALLBACK)
# ===================================================================


def refine_seeds(
    client: LLMClient,
    seeds_df: pd.DataFrame,
    max_samples_per_cat: int = 20,
) -> List[Dict]:
    """
    Synchronous wrapper for Stage 2 refinement.

    Prefer ``refine_seeds_async`` in async contexts.
    """
    refiner = SemanticRefiner()
    results = []

    for cat_code, group in seeds_df.groupby("cat_code"):
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
                    temperature=0.3,
                )
                ok, parsed, err = parse_json(raw)
                if not ok:
                    logger.warning(
                        f"Refine JSON parse failed: {err}. Using seed as fallback."
                    )
                    results.append(
                        {
                            "seed": seed,
                            "cat_code": cat_code,
                            "refined_mold": seed,
                            "preserved_intent": "",
                        }
                    )
                else:
                    results.append(
                        {
                            "seed": seed,
                            "cat_code": cat_code,
                            "refined_mold": parsed.get("refined_prompt", seed),
                            "preserved_intent": parsed.get("preserved_intent", ""),
                        }
                    )
            except Exception as exc:
                logger.error(f"Refine failed for seed '{seed[:60]}...': {exc}")
                results.append(
                    {
                        "seed": seed,
                        "cat_code": cat_code,
                        "refined_mold": seed,
                        "preserved_intent": "",
                    }
                )

    logger.info(f"Refine complete: {len(results)} molds created")
    return results


# ===================================================================
# STAGE 3 (SYNC FALLBACK)
# ===================================================================


def localize_molds(
    client: LLMClient,
    refined_molds: List[Dict],
) -> List[Dict]:
    """
    Synchronous wrapper for Stage 3 translation.

    Prefer ``localize_molds_async`` in async contexts.
    """
    translator = VietnameseTranslator()
    validator = PromptValidator()
    results = []

    for i, mold_entry in enumerate(refined_molds):
        mold_text = mold_entry.get("refined_mold", "")
        cat_code = mold_entry.get("cat_code", "A")
        content = get_content_for_category(cat_code)
        content_context = json.dumps(content, ensure_ascii=False, indent=2)
        prompt = translator.build_translator_prompt(
            mold_text, cat_code, content_context=content_context
        )

        try:
            raw = client.generate_json(
                input_text=prompt,
                system_prompt=translator.system_prompt,
                temperature=0.7,
            )
            ok, parsed, err = parse_json(raw)
            if not ok:
                logger.warning(
                    f"Translate JSON parse failed for mold {i}: {err}"
                )
                results.append(
                    {
                        **mold_entry,
                        "vietnamese_prompt": mold_text,
                        "filled_slots_vn": {},
                        "cultural_anchors": [],
                        "parse_error": err,
                    }
                )
                continue

            vn_prompt = parsed.get("vietnamese_prompt", "")

            # Validate
            is_valid, reason = validator.validate_single(vn_prompt, cat_code)
            if not is_valid:
                logger.warning(
                    f"Validation failed for prompt {i}: {reason}. Saving anyway."
                )

            results.append(
                {
                    **mold_entry,
                    "vietnamese_prompt": vn_prompt,
                    "filled_slots_vn": parsed.get("filled_slots_vn", {}),
                    "cultural_anchors": parsed.get("cultural_anchors", []),
                    "validation": {"valid": is_valid, "reason": reason},
                }
            )
        except Exception as exc:
            logger.error(f"Translate failed for mold {i}: {exc}")
            results.append(
                {
                    **mold_entry,
                    "vietnamese_prompt": mold_text,
                    "filled_slots_vn": {},
                    "cultural_anchors": [],
                }
            )

    logger.info(f"Localize complete: {len(results)} prompts generated")
    return results


# ===================================================================
# Export
# ===================================================================


def export_dataset(
    results: List[Dict],
    output_dir: str,
    output_filename: str = "vieset_benchmark.csv",
    include_refined: bool = False,
) -> str:
    """Export generated prompts to CSV."""
    if not results:
        logger.warning("No results to export")
        return ""

    os.makedirs(output_dir, exist_ok=True)

    # Build output columns compatible with the evaluate pipeline
    rows = []
    for r in results:
        row = {
            "domain": "",
            "category": CAT_CODE_TO_VN.get(r.get("cat_code", ""), ""),
            "cat_code": r.get("cat_code", ""),
            "seed": r.get("seed", ""),
            "vietnamese_prompt": r.get("vietnamese_prompt", ""),
            "preserved_intent": r.get("preserved_intent", ""),
            "cultural_anchors": json.dumps(
                r.get("cultural_anchors", []), ensure_ascii=False
            ),
        }
        if include_refined:
            row["refined_mold"] = r.get("refined_mold", "")
        rows.append(row)

    df = pd.DataFrame(rows)
    output_path = os.path.join(output_dir, output_filename)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(f"Exported {len(df)} records to {output_path}")
    return output_path


# ===================================================================
# Validation & Dedup
# ===================================================================


def validate_and_dedup(results: List[Dict]) -> Tuple[List[Dict], Dict]:
    """Apply PromptValidator and dedup to all results."""
    validator = PromptValidator()
    prompts = [r.get("vietnamese_prompt", "") for r in results]
    cat_codes = [r.get("cat_code", "") for r in results]

    valid_prompts, valid_cats, _, stats = validator.filter_valid(prompts, cat_codes)

    final = [
        r
        for r in results
        if r.get("vietnamese_prompt", "") in set(valid_prompts)
    ]

    # Deduplicate
    seen = set()
    deduped = []
    removed = 0
    for r in final:
        norm = " ".join(r.get("vietnamese_prompt", "").strip().lower().split())
        if norm in seen:
            removed += 1
            continue
        seen.add(norm)
        deduped.append(r)

    dedup_stats = {**stats, "duplicates_removed": removed}
    logger.info(
        f"Validation+Dedup: {len(deduped)} kept, "
        f"{stats['invalid']} invalid, {removed} duplicates"
    )
    return deduped, dedup_stats


# ===================================================================
# Orchestrator
# ===================================================================


async def run_pipeline_async(
    seed_path: str = DEFAULT_SEED_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    output_filename: str = "vieset_benchmark.csv",
    model: str = "gpt-4.1",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_per_category: int = 20,
    skip_refine: bool = False,
    max_concurrency: int = 5,
    checkpoint_dir: Optional[str] = None,
    # Column name overrides
    seed_prompt_col: str = "seed",
    seed_category_col: str = "category",
    seed_domain_col: str = "domain",
    seed_response_col: str = "response",
    include_refined: bool = False,
    enable_auto_label: bool = True,
    enable_dynamic_content: bool = False,
) -> tuple:
    """
    Run the full 3-stage CAGE pipeline asynchronously.

    Phase 2 additions:
    - ``enable_auto_label``: use LLM-based AutoLabeler for seed category mapping
    - ``enable_dynamic_content``: fetch and inject scraped VN news/legal content

    Returns (output_path, stats_dict).
    """
    stats: Dict[str, object] = {}

    # -- Setup ---------------------------------------------------------------
    if checkpoint_dir is None:
        checkpoint_dir = DEFAULT_CHECKPOINT_DIR
    chkpt = CheckpointManager(checkpoint_dir)

    client = LLMClient(model=model, api_key=api_key, base_url=base_url)
    engine = AsyncPipelineEngine(
        client, max_concurrency=max_concurrency, checkpoint_manager=chkpt
    )

    # -- Stage 1: Collect seeds ----------------------------------------------
    logger.info("=" * 50)
    logger.info("STAGE 1: Seed Collection")
    logger.info("=" * 50)
    # Phase 2: Optional auto-labeling and dynamic content
    auto_labeler = None
    if enable_auto_label:
        auto_labeler = AutoLabeler(client=client)

    if enable_dynamic_content:
        logger.info("Fetching dynamic content from Vietnamese sources...")
        try:
            from generate.scraping.vnexpress import VnExpressScraper
            from generate.scraping.base import ScraperCache
            cache = ScraperCache()
            vne = VnExpressScraper(cache=cache, max_articles=30)
            articles = await vne.get_articles()
            # Map scraped articles to category hints and inject
            for art in articles:
                for tag in art.tags:
                    if len(tag) == 1 and tag in "ABCDEFGHIJKL":
                        inject_dynamic_content(tag, [art])
                        break
            logger.info("Injected %d dynamic articles into content repo", len(articles))
        except Exception as exc:
            logger.warning("Dynamic content fetch failed (continuing without): %s", exc)

    seeds_df = await collect_seeds(
        seed_path,
        prompt_col=seed_prompt_col,
        category_col=seed_category_col,
        domain_col=seed_domain_col,
        response_col=seed_response_col,
        auto_labeler=auto_labeler,
    )
    stats["total_seeds"] = len(seeds_df)
    stats["categories"] = seeds_df["cat_code"].nunique()

    # Try to load existing checkpoints for resume
    refined_molds = await chkpt.load("refine_mold_success")
    localized = await chkpt.load("localize")

    # Filter seeds_df to skip already-processed seeds on resume
    if refined_molds:
        processed_indices = {
            m.get("seed_index") for m in refined_molds if "seed_index" in m
        }
        if processed_indices and -1 not in processed_indices:
            before = len(seeds_df)
            seeds_df = seeds_df[~seeds_df.index.isin(processed_indices)]
            after = len(seeds_df)
            logger.info(
                "Checkpoint resume: filtered %d already-processed seeds, %d remaining",
                before - after, after,
            )

    if not refined_molds:
        # -- Stage 2: Refine-with-Slot ---------------------------------------
        logger.info("=" * 50)
        logger.info("STAGE 2: Refine-with-Slot (async)")
        logger.info("=" * 50)
        if skip_refine:
            logger.info("Skipping refinement (--skip_refine)")
            refined_molds = [
                {"seed": row["seed"], "cat_code": row["cat_code"], "refined_mold": row["seed"]}
                for _, row in seeds_df.iterrows()
            ]
        else:
            refined_molds = await refine_seeds_async(
                client, engine, seeds_df, max_per_category
            )
            # Save success checkpoint
            await chkpt.save("refine_mold_success", refined_molds)
        stats["refined_molds"] = len(refined_molds)
    else:
        logger.info(
            "Resumed %d refined molds from checkpoint", len(refined_molds)
        )
        stats["refined_molds"] = len(refined_molds)

    if not localized:
        # -- Stage 3: Translate-with-Context ---------------------------------
        logger.info("=" * 50)
        logger.info("STAGE 3: Translate-with-Context (async)")
        logger.info("=" * 50)
        localized = await localize_molds_async(client, engine, refined_molds)
        await chkpt.save("localize", localized)
        stats["localized_prompts"] = len(localized)
    else:
        logger.info(
            "Resumed %d localized prompts from checkpoint", len(localized)
        )
        stats["localized_prompts"] = len(localized)

    # -- Validate & Dedup ---------------------------------------------------
    final, val_stats = validate_and_dedup(localized)
    stats.update(val_stats)

    # -- Export --------------------------------------------------------------
    logger.info("=" * 50)
    logger.info("EXPORT: Saving Final Dataset")
    logger.info("=" * 50)
    output_path = export_dataset(
        final, output_dir, output_filename, include_refined
    )

    # -- Usage summary -------------------------------------------------------
    usage = client.usage_summary
    stats["total_tokens"] = usage["total_tokens"]
    stats["total_cost_usd"] = usage["total_cost_usd"]
    logger.info(f"Total tokens: {usage['total_tokens']}")
    logger.info(f"Estimated cost: ${usage['total_cost_usd']:.6f}")

    return output_path, stats


def run_pipeline(
    seed_path: str = DEFAULT_SEED_PATH,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    output_filename: str = "vieset_benchmark.csv",
    model: str = "gpt-4.1",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    max_per_category: int = 20,
    skip_refine: bool = False,
    max_concurrency: int = 5,
    checkpoint_dir: Optional[str] = None,
    # Column name overrides
    seed_prompt_col: str = "seed",
    seed_category_col: str = "category",
    seed_domain_col: str = "domain",
    seed_response_col: str = "response",
    include_refined: bool = False,
) -> tuple:
    """
    Synchronous entry point that delegates to async pipeline via asyncio.run.

    Returns (output_path, stats_dict).
    """
    return asyncio.run(
        run_pipeline_async(
            seed_path=seed_path,
            output_dir=output_dir,
            output_filename=output_filename,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_per_category=max_per_category,
            skip_refine=skip_refine,
            max_concurrency=max_concurrency,
            checkpoint_dir=checkpoint_dir,
            seed_prompt_col=seed_prompt_col,
            seed_category_col=seed_category_col,
            seed_domain_col=seed_domain_col,
            seed_response_col=seed_response_col,
            include_refined=include_refined,
        )
    )


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
        help="Generator model (default: gpt-4.1). Use 'deepseek/deepseek-chat' for DeepSeek.",
    )
    parser.add_argument(
        "--api_key", "-a",
        default=None,
        help="API key (default: from environment variable)",
    )
    parser.add_argument(
        "--base_url",
        default=None,
        help="Custom base URL for API (e.g., https://api.deepseek.com for DeepSeek)",
    )
    parser.add_argument(
        "--max_per_category",
        type=int,
        default=20,
        help="Max seeds to generate per category (default: 20)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent LLM calls (default: 5)",
    )
    parser.add_argument(
        "--checkpoint_dir",
        default=None,
        help="Directory for incremental checkpoints (default: ../checkpoints)",
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
        "--enable_auto_label",
        action="store_true",
        default=True,
        help="Use LLM-based AutoLabeler for seed category mapping (default: on)",
    )
    parser.add_argument(
        "--no_auto_label",
        action="store_false",
        dest="enable_auto_label",
        help="Disable LLM auto-labeling, use heuristic fallback only",
    )
    parser.add_argument(
        "--dynamic_content",
        action="store_true",
        default=False,
        help="Fetch dynamic content from VN news/legal sources before generation",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Load seeds and print stats without generating",
    )

    args = parser.parse_args()

    if args.dry_run:
        async def _dry():
            return await collect_seeds(
                args.input,
                prompt_col=args.prompt_col,
                category_col=args.category_col,
                domain_col=args.domain_col,
                response_col=args.response_col,
            )
        seeds_df = asyncio.run(_dry())
        print("\nSeed summary:")
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
        base_url=args.base_url,
        max_per_category=args.max_per_category,
        skip_refine=args.skip_refine,
        max_concurrency=args.concurrency,
        checkpoint_dir=args.checkpoint_dir,
        seed_prompt_col=args.prompt_col,
        seed_category_col=args.category_col,
        seed_domain_col=args.domain_col,
        seed_response_col=args.response_col,
        include_refined=args.include_refined,
        enable_auto_label=args.enable_auto_label,
        enable_dynamic_content=args.dynamic_content,
    )

    print("\n=== VieSet Generation Complete ===")
    print(f"Output:          {output_path}")
    print(f"Total prompts:   {stats.get('localized_prompts', 0)}")
    print(f"Total tokens:    {stats.get('total_tokens', 0)}")
    print(f"Estimated cost:  ${stats.get('total_cost_usd', 0):.6f}")
    print("\nTo evaluate: python run/safety_judge.py -i {output_path} "
          f"-d results -o result_vn.csv -m prompt -l vn -a YOUR_API_KEY")


if __name__ == "__main__":
    main()
