"""
Async Pipeline Engine and CheckpointManager for the CAGE Generation Pipeline.

Provides:
- ``AsyncPipelineEngine``: concurrent async generation with semaphore control
- ``CheckpointManager``: incremental save/restore for fault tolerance
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiofiles
import aiofiles.os as aiofiles_os

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """
    Incremental checkpointing for long-running generation pipelines.

    Saves results in JSONL format after each batch so a crash at prompt
    N-1 out of N does not lose all preceding data.
    """

    def __init__(self, checkpoint_dir: str) -> None:
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, stage: str) -> Path:
        return self.dir / f"checkpoint_{stage}.jsonl"

    async def save(self, stage: str, records: List[Dict[str, Any]]) -> None:
        """Append records to the checkpoint file for *stage* as JSONL."""
        path = self._path(stage)
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            for rec in records:
                await f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logger.debug("Checkpoint %s: saved %d records to %s", stage, len(records), path)

    async def load(self, stage: str) -> List[Dict[str, Any]]:
        """Load all records from the checkpoint file for *stage*."""
        path = self._path(stage)
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        logger.info("Checkpoint %s: loaded %d records from %s", stage, len(records), path)
        return records

    async def clear(self, stage: str) -> None:
        """Delete the checkpoint file for *stage*."""
        path = self._path(stage)
        if path.exists():
            await aiofiles_os.remove(path)


# ---------------------------------------------------------------------------
# AsyncPipelineEngine
# ---------------------------------------------------------------------------

class AsyncPipelineEngine:
    """
    Async pipeline engine for concurrent LLM generation.

    Wraps an ``LLMClient`` with an ``asyncio.Semaphore`` to bound
    concurrency, runs a list of generation tasks via ``asyncio.gather``,
    and supports incremental checkpointing.

    Parameters
    ----------
    client :
        The ``LLMClient`` (or compatible) instance used for generation.
    max_concurrency : int
        Maximum number of simultaneous LLM calls (default 5).
    checkpoint_manager : CheckpointManager, optional
        If provided, results are saved incrementally after each batch.
    """

    def __init__(
        self,
        client: Any,  # LLMClient (avoid circular import in type hint)
        max_concurrency: int = 5,
        checkpoint_manager: Optional[CheckpointManager] = None,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.checkpoint = checkpoint_manager
        logger.info(
            "AsyncPipelineEngine initialized with max_concurrency=%d",
            max_concurrency,
        )

    async def _run_one(
        self,
        index: int,
        task_fn: Callable[[], Any],
    ) -> Tuple[int, Any, Optional[Exception]]:
        """
        Run a single task under the semaphore, returning (index, result, error).
        """
        async with self.semaphore:
            try:
                result = await task_fn()
                return index, result, None
            except Exception as exc:
                logger.error("Task %d failed: %s", index, exc)
                return index, None, exc

    async def run(
        self,
        tasks: List[Callable[[], Any]],
        stage: str = "default",
        checkpoint_batch: int = 10,
    ) -> List[Tuple[int, Any, Optional[Exception]]]:
        """
        Run all *tasks* concurrently with bounded parallelism.

        Parameters
        ----------
        tasks :
            List of async callables, each returning a result.
        stage :
            Label used for checkpointing (e.g. "refine", "localize").
        checkpoint_batch :
            Save checkpoint after every N completed tasks.

        Returns
        -------
        List of ``(index, result, error)`` tuples in the original order.
        """
        total = len(tasks)
        logger.info("Stage '%s': starting %d tasks", stage, total)

        # Launch all tasks under semaphore control
        coros = [self._run_one(i, fn) for i, fn in enumerate(tasks)]
        ordered_results: List[Optional[Tuple[int, Any, Optional[Exception]]]] = [
            None
        ] * total
        completed = 0
        successes = 0
        failures = 0

        # Track completed tasks and checkpoint periodically
        pending = set(range(total))
        task_map = {asyncio.ensure_future(c): i for i, c in enumerate(coros)}

        while pending:
            done, _ = await asyncio.wait(
                [t for t in task_map if not t.done()],
                return_when=asyncio.FIRST_COMPLETED,
            )
            batch_completed: List[Dict[str, Any]] = []

            for fut in done:
                idx = task_map[fut]
                pending.discard(idx)
                completed += 1
                try:
                    _, result, error = fut.result()
                except Exception as exc:
                    result, error = None, exc

                ordered_results[idx] = (idx, result, error)
                if error is None:
                    successes += 1
                    if result is not None:
                        batch_completed.append(result)
                else:
                    failures += 1

            # Checkpoint
            if (
                self.checkpoint is not None
                and batch_completed
                and completed % checkpoint_batch == 0
            ):
                await self.checkpoint.save(stage, batch_completed)

            logger.debug(
                "Stage '%s': %d/%d done (%d ok, %d failed)",
                stage,
                completed,
                total,
                successes,
                failures,
            )

        # Final checkpoint flush
        if self.checkpoint is not None:
            all_ok = [
                r
                for (_, r, e) in ordered_results
                if r is not None and e is None
            ]
            if all_ok:
                await self.checkpoint.save(stage, all_ok)

        logger.info(
            "Stage '%s': complete. %d/%d succeeded, %d failed.",
            stage,
            successes,
            total,
            failures,
        )

        return ordered_results  # type: ignore[return-value]
