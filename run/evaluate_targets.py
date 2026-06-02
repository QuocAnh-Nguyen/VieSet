"""
VieSet / CAGE — Target Model Evaluator (Phase 4)

End-to-end evaluation workflow:
  1. Load generated benchmark prompts (from ``generate_vieset.py`` output CSV)
  2. Send each prompt to a **target LLM** under test
  3. Pass the target's response through the **safety judge**
  4. Produce analytics (per-category ASR, domain summaries, reports)

Supports any LLM reachable via litellm:
  - OpenAI models (gpt-4.1, gpt-4o, o3, o4-mini, ...)
  - DeepSeek (deepseek/deepseek-chat, deepseek/deepseek-reasoner)
  - Anthropic (claude-sonnet-4-20250514, ...)
  - Google Gemini (gemini/gemini-2.5-pro, ...)
  - Local vLLM / Ollama via ``--base_url``

Architecture:
  Phase 1 ``LLMClient``  →  target inference  (async, retry, cost-tracked)
  Phase 1 ``LLMClient``  →  safety judge       (async, retry, cost-tracked)
  Phase 1 ``AsyncPipelineEngine``  →  concurrency control + checkpointing
  Phase 4 ``EvaluationReporter``  →  analytics
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
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Ensure the VieSet package is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from generate.base.llm_client import LLMClient
from generate.base.async_engine import AsyncPipelineEngine, CheckpointManager
from evaluate.analytics.reporter import EvaluationReporter
from run.safety_judge import (
    CustomJudge,
    parse_result_from_json,
    _strip_markdown,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "evaluate_targets.log")),
    ],
)
logger = logging.getLogger("evaluate_targets")

# ---------------------------------------------------------------------------
# Target model registry — easy to extend
# ---------------------------------------------------------------------------
TARGET_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gpt-4.1": {
        "name": "GPT-4.1",
        "provider": "openai",
        "base_url": None,
        "description": "OpenAI GPT-4.1",
    },
    "gpt-4.1-mini": {
        "name": "GPT-4.1 Mini",
        "provider": "openai",
        "base_url": None,
        "description": "OpenAI GPT-4.1 Mini (cost-efficient)",
    },
    "gpt-4o": {
        "name": "GPT-4o",
        "provider": "openai",
        "base_url": None,
        "description": "OpenAI GPT-4o (omni)",
    },
    "gpt-4o-mini": {
        "name": "GPT-4o Mini",
        "provider": "openai",
        "base_url": None,
        "description": "OpenAI GPT-4o Mini",
    },
    "deepseek/deepseek-chat": {
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "description": "DeepSeek V3 / DeepSeek Chat",
    },
    "deepseek/deepseek-reasoner": {
        "name": "DeepSeek R1",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "description": "DeepSeek R1 (reasoning model)",
    },
    "claude-sonnet-4-20250514": {
        "name": "Claude Sonnet 4",
        "provider": "anthropic",
        "base_url": None,
        "description": "Anthropic Claude Sonnet 4",
    },
    "gemini/gemini-2.5-pro": {
        "name": "Gemini 2.5 Pro",
        "provider": "google",
        "base_url": None,
        "description": "Google Gemini 2.5 Pro",
    },
}


def register_target(name: str, model: str, provider: str,
                    base_url: Optional[str] = None,
                    description: str = "") -> None:
    """Register a custom target model at runtime."""
    TARGET_MODEL_REGISTRY[model] = {
        "name": name,
        "provider": provider,
        "base_url": base_url,
        "description": description,
    }


# ===================================================================
# Target inference
# ===================================================================
async def infer_targets(
    target_client: LLMClient,
    engine: AsyncPipelineEngine,
    prompts: List[str],
    target_name: str,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Send each benchmark prompt to the target model and collect responses.

    Returns list of dicts with ``prompt``, ``response``, ``error``.
    """
    async def _call_one(prompt: str) -> Dict[str, Any]:
        try:
            response = await target_client.agenerate(
                input_text=prompt,
                system_prompt="You are a helpful assistant.",
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return {"prompt": prompt, "response": response, "error": None}
        except Exception as exc:
            logger.warning("Target inference failed: %s", exc)
            return {"prompt": prompt, "response": "", "error": str(exc)}

    tasks = [lambda p=p: _call_one(p) for p in prompts]  # type: ignore[misc]
    results_raw = await engine.run(
        tasks=tasks,
        stage=f"infer_{target_name.replace('/', '_')}",
        checkpoint_batch=20,
    )

    results: List[Dict[str, Any]] = []
    for idx, result, error in results_raw:
        if error is not None:
            results.append({
                "prompt": prompts[idx] if idx < len(prompts) else "",
                "response": "",
                "error": str(error),
            })
        elif result is not None:
            results.append(result)
        else:
            results.append({
                "prompt": prompts[idx] if idx < len(prompts) else "",
                "response": "",
                "error": "unknown",
            })

    return results


# ===================================================================
# Safety judging
# ===================================================================
async def judge_responses(
    judge: CustomJudge,
    engine: AsyncPipelineEngine,
    df: pd.DataFrame,
    prompt_col: str = "vietnamese_prompt",
    response_col: str = "response",
    lang: str = "vn",
    mode: str = "prompt",
) -> pd.DataFrame:
    """
    Pass each (prompt, response) pair through the safety judge.

    Dynamically loads the appropriate language-specific safety rubric.
    """
    # Dynamic module loading (mirrors safety_judge.py)
    module_name = "prompt_guard" if mode == "prompt" else "prompt_response_guard"
    module_path = f"evaluate.template.{lang}.{module_name}"

    try:
        target_module = __import__(module_path, fromlist=["SYSTEM_PROMPT"])
    except ModuleNotFoundError as e:
        logger.warning("Module %s not found, falling back to vn: %s", module_path, e)
        target_module = __import__(
            "evaluate.template.vn.prompt_guard", fromlist=["SYSTEM_PROMPT"]
        )

    class_name = (
        "Prompt_Harmfulness" if mode == "prompt"
        else "Prompt_Response_Harmfulness"
    )
    PrompterClass = getattr(target_module, class_name)
    SYSTEM_PROMPT = getattr(target_module, "SYSTEM_PROMPT")
    prompter = PrompterClass()

    # Build judge prompts
    prompts_list = df[prompt_col].tolist()
    cat_col_name = "cat_code" if "cat_code" in df.columns else "category"
    categories_list = (
        df[cat_col_name].tolist()
        if cat_col_name in df.columns
        else ["A"] * len(df)
    )

    if mode == "prompt":
        user_prompts = prompter.generate_promptchunks(prompts_list, categories_list)
    else:
        if response_col not in df.columns:
            raise ValueError(f"Response column '{response_col}' not found")
        responses_list = df[response_col].tolist()
        user_prompts = prompter.generate_promptchunks(
            prompts_list, responses_list, categories_list
        )

    # Judge with semaphore
    sem = asyncio.Semaphore(engine.semaphore._value)

    async def judge_one(idx: int, uprompt: str) -> Dict[str, str]:
        async with sem:
            try:
                raw = await judge.judge(SYSTEM_PROMPT, uprompt)
                result_val = parse_result_from_json(raw)
                return {"raw_output": raw, "result": result_val}
            except Exception as exc:
                logger.error("Judge error at idx %d: %s", idx, exc)
                return {"raw_output": str(exc), "result": "Error"}

    logger.info("Judging %d responses...", len(user_prompts))
    tasks = [judge_one(i, p) for i, p in enumerate(user_prompts)]
    results = await asyncio.gather(*tasks)

    # Merge results
    results_df = pd.DataFrame(results)
    out_df = pd.concat([df.reset_index(drop=True), results_df.reset_index(drop=True)], axis=1)
    out_df["judge"] = out_df["result"].apply(lambda x: "Yes" if x == "X" else "No")
    out_df["safe_rubric"] = out_df["result"].apply(
        lambda x: "No" if x == "X" else "Yes"
    )

    return out_df


# ===================================================================
# Main async pipeline
# ===================================================================
async def run_evaluation(
    benchmark_csv: str,
    target_model: str,
    target_api_key: Optional[str],
    target_base_url: Optional[str],
    judge_model: str,
    judge_api_key: Optional[str],
    judge_base_url: Optional[str],
    output_dir: str,
    output_basename: str,
    prompt_col: str = "vietnamese_prompt",
    category_col: str = "cat_code",
    max_prompts: int = 0,
    target_max_tokens: int = 2048,
    target_temperature: float = 0.0,
    max_concurrency: int = 5,
    lang: str = "vn",
    mode: str = "prompt",
    checkpoint_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Full evaluation pipeline: load → infer → judge → report.

    Returns (output_csv_path, stats_dict).
    """
    t0 = time.monotonic()

    # --- 1. Load benchmark prompts ------------------------------------------
    if not os.path.exists(benchmark_csv):
        raise FileNotFoundError(f"Benchmark CSV not found: {benchmark_csv}")

    logger.info("Loading benchmark: %s", benchmark_csv)
    df = pd.read_csv(benchmark_csv, keep_default_na=False)

    if prompt_col not in df.columns:
        available = list(df.columns)
        # Attempt fallback: "seed", "vietnamese_prompt", first column
        for fallback in ["vietnamese_prompt", "seed", "prompt"]:
            if fallback in df.columns:
                prompt_col = fallback
                break
        else:
            raise ValueError(
                f"Prompt column '{prompt_col}' not found. "
                f"Available: {available}"
            )

    if max_prompts > 0 and len(df) > max_prompts:
        logger.info("Sampling %d/%d prompts", max_prompts, len(df))
        df = df.sample(n=max_prompts, random_state=42).reset_index(drop=True)

    prompts = df[prompt_col].tolist()
    logger.info("Loaded %d benchmark prompts", len(prompts))

    # Ensure cat_code exists
    if "cat_code" not in df.columns and category_col in df.columns:
        df["cat_code"] = df[category_col].astype(str)

    # --- 2. Target inference ------------------------------------------------
    if checkpoint_dir is None:
        checkpoint_dir = os.path.join(output_dir, "checkpoints")
    chkpt = CheckpointManager(checkpoint_dir)

    target_client = LLMClient(
        model=target_model,
        api_key=target_api_key,
        base_url=target_base_url,
    )
    target_engine = AsyncPipelineEngine(
        client=target_client,
        max_concurrency=max_concurrency,
        checkpoint_manager=chkpt,
    )

    logger.info("=" * 50)
    logger.info("STAGE A: Target Model Inference")
    logger.info("  Model:  %s", target_model)
    logger.info("  Prompts: %d", len(prompts))
    logger.info("=" * 50)

    responses = await infer_targets(
        target_client=target_client,
        engine=target_engine,
        prompts=prompts,
        target_name=target_model.replace("/", "_"),
        max_tokens=target_max_tokens,
        temperature=target_temperature,
    )

    # Merge responses into dataframe
    resp_df = pd.DataFrame(responses)
    df = pd.concat([df.reset_index(drop=True), resp_df.reset_index(drop=True)], axis=1)

    # --- 3. Safety judging --------------------------------------------------
    judge_client = CustomJudge(
        model=judge_model,
        api_key=judge_api_key,
        base_url=judge_base_url,
    )
    judge_engine = AsyncPipelineEngine(
        client=judge_client.client,
        max_concurrency=max_concurrency,
        checkpoint_manager=chkpt,
    )

    logger.info("=" * 50)
    logger.info("STAGE B: Safety Judging")
    logger.info("  Judge:  %s", judge_model)
    logger.info("  Lang:   %s  |  Mode: %s", lang, mode)
    logger.info("=" * 50)

    judged = await judge_responses(
        judge=judge_client,
        engine=judge_engine,
        df=df,
        prompt_col=prompt_col,
        response_col="response",
        lang=lang,
        mode=mode,
    )

    # --- 4. Save results ----------------------------------------------------
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{output_basename}.csv")
    judged.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("Results saved to %s", output_path)

    # --- 5. Analytics -------------------------------------------------------
    reporter = EvaluationReporter(judged)
    reporter.print_report()
    report_paths = reporter.save_report(output_dir, output_basename)

    # --- 6. Cost summary ----------------------------------------------------
    target_usage = target_client.usage_summary
    judge_usage = judge_client.client.usage_summary
    total_cost = target_usage["total_cost_usd"] + judge_usage["total_cost_usd"]

    elapsed = time.monotonic() - t0
    stats: Dict[str, Any] = {
        "target_model": target_model,
        "judge_model": judge_model,
        "total_prompts": len(prompts),
        "target_tokens": target_usage["total_tokens"],
        "target_cost_usd": round(target_usage["total_cost_usd"], 6),
        "judge_tokens": judge_usage["total_tokens"],
        "judge_cost_usd": round(judge_usage["total_cost_usd"], 6),
        "total_cost_usd": round(total_cost, 6),
        "elapsed_seconds": round(elapsed, 1),
        "output_csv": output_path,
        "reports": report_paths,
        "evaluation": reporter.overall_stats(),
    }

    logger.info("Total cost: $%.6f  |  Elapsed: %.1fs", total_cost, elapsed)
    logger.info("Evaluation complete. ASR: %.1f%%",
                stats["evaluation"]["asr"] * 100)

    return output_path, stats


# ===================================================================
# CLI
# ===================================================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="VieSet / CAGE — Target Model Evaluator (Phase 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate GPT-4.1 against the benchmark, judged by GPT-4.1
  python run/evaluate_targets.py -i data/vieset_benchmark.csv \\
      --target gpt-4.1 --judge gpt-4.1 -a $OPENAI_API_KEY

  # Evaluate DeepSeek against the benchmark
  python run/evaluate_targets.py -i data/vieset_benchmark.csv \\
      --target deepseek/deepseek-chat --target-key $DEEPSEEK_KEY \\
      --judge gpt-4.1 -a $OPENAI_API_KEY

  # Test a local vLLM model
  python run/evaluate_targets.py -i data/vieset_benchmark.csv \\
      --target openai/Llama-3-8B --target-base http://localhost:8000/v1 \\
      --judge gpt-4.1 -a $OPENAI_API_KEY
""",
    )

    # Input / Output
    parser.add_argument(
        "--input", "-i", default=None,
        help="Benchmark CSV (output of generate_vieset.py)",
    )
    parser.add_argument(
        "--outdir", "-d", default="results",
        help="Output directory (default: results)",
    )
    parser.add_argument(
        "--outfile", "-o", default=None,
        help="Output basename (default: auto-generated from model names)",
    )

    # Columns
    parser.add_argument(
        "--prompt_col", "-pc", default="vietnamese_prompt",
        help="Column with benchmark prompts (default: vietnamese_prompt)",
    )
    parser.add_argument(
        "--category_col", "-cc", default="cat_code",
        help="Column with CAGE category codes (default: cat_code)",
    )

    # Target model
    parser.add_argument(
        "--target", "-t", default=None,
        help="Target model to evaluate (litellm format, e.g. gpt-4.1, deepseek/deepseek-chat)",
    )
    parser.add_argument(
        "--target-key", default=None,
        help="API key for target model (default: env var)",
    )
    parser.add_argument(
        "--target-base", default=None,
        help="Custom base URL for target model (e.g., http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--target-max-tokens", type=int, default=2048,
        help="Max tokens for target response (default: 2048)",
    )
    parser.add_argument(
        "--target-temperature", type=float, default=0.0,
        help="Temperature for target generation (default: 0.0)",
    )

    # Judge model
    parser.add_argument(
        "--judge", "-j", default="gpt-4.1",
        help="Safety judge model (default: gpt-4.1)",
    )
    parser.add_argument(
        "--api_key", "-a", default=None,
        help="API key for judge model (default: env var)",
    )
    parser.add_argument(
        "--judge-base", default=None,
        help="Custom base URL for judge model",
    )

    # Execution
    parser.add_argument(
        "--concurrency", type=int, default=5,
        help="Max concurrent calls (default: 5)",
    )
    parser.add_argument(
        "--max_prompts", type=int, default=0,
        help="Limit to N prompts (0 = all)",
    )
    parser.add_argument(
        "--lang", "-l", default="vn",
        choices=["en", "ko", "vn"],
        help="Language for safety rubric (default: vn)",
    )
    parser.add_argument(
        "--mode", "-m", default="prompt",
        choices=["prompt", "response"],
        help="Evaluation mode: prompt or response (default: prompt)",
    )

    # Registry and listing
    parser.add_argument(
        "--list-targets", action="store_true",
        help="List registered target models and exit",
    )

    args = parser.parse_args()

    # Validate required args when not listing targets
    if not args.list_targets:
        if not args.input:
            parser.error("--input/-i is required")
        if not args.target:
            parser.error("--target/-t is required")

    # List targets
    if args.list_targets:
        print("\nRegistered target models:\n")
        for model_id, info in TARGET_MODEL_REGISTRY.items():
            print(f"  {model_id:<35s}  {info['name']:<20s}  ({info['provider']})")
            print(f"  {'':35s}  {info['description']}")
            print()
        return

    # Auto-generate output basename
    if args.outfile is None:
        target_short = args.target.replace("/", "_").replace(":", "_")
        judge_short = args.judge.replace("/", "_").replace(":", "_")
        args.outfile = f"eval_{target_short}_judgedby_{judge_short}"

    # Run
    output_path, stats = asyncio.run(
        run_evaluation(
            benchmark_csv=args.input,
            target_model=args.target,
            target_api_key=args.target_key,
            target_base_url=args.target_base,
            judge_model=args.judge,
            judge_api_key=args.api_key,
            judge_base_url=args.judge_base,
            output_dir=args.outdir,
            output_basename=args.outfile,
            prompt_col=args.prompt_col,
            category_col=args.category_col,
            max_prompts=args.max_prompts,
            target_max_tokens=args.target_max_tokens,
            target_temperature=args.target_temperature,
            max_concurrency=args.concurrency,
            lang=args.lang,
            mode=args.mode,
        )
    )

    print(f"\n=== Evaluation Complete ===")
    print(f"Output CSV:     {output_path}")
    print(f"Target model:   {args.target}")
    print(f"Judge model:    {args.judge}")
    print(f"Total prompts:  {stats['total_prompts']}")
    print(f"Total cost:     ${stats['total_cost_usd']:.6f}")
    print(f"Elapsed:        {stats['elapsed_seconds']:.1f}s")


if __name__ == "__main__":
    main()
