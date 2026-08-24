"""Thin frozen-manifest scaling driver over the production scheduler."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from firstgreen.config import Manifest
from firstgreen.reporting.trace import runtime_observability
from firstgreen.service import SchedulerService


@dataclass(frozen=True)
class ScalingCell:
    slots: int
    repetition: int
    run_id: str
    makespan_seconds: float
    verified: int
    failed: int


def write_scaling_svg(results: list[dict[str, Any]], path: Path) -> Path:
    """Write a dependency-free speedup figure from valid matrix cells."""

    cells = [
        (int(row["slots"]), float(row["speedup_vs_first_one_slot"]))
        for row in results
        if row.get("failed") == 0 and row.get("speedup_vs_first_one_slot") is not None
    ]
    if not cells:
        raise ValueError("a scaling figure requires at least one valid cell")
    cells.sort()
    width, height = 720, 420
    left, right, top, bottom = 72, 24, 32, 62
    plot_width = width - left - right
    plot_height = height - top - bottom
    max_slot = max(slot for slot, _ in cells)
    max_speedup = max(1.0, max(speedup for _, speedup in cells))

    def x(slot: int) -> float:
        return left + plot_width * ((slot - 1) / max(1, max_slot - 1))

    def y(speedup: float) -> float:
        return top + plot_height * (1 - speedup / max_speedup)

    points = " ".join(f"{x(slot):.1f},{y(speedup):.1f}" for slot, speedup in cells)
    labels = "".join(
        f'<circle cx="{x(slot):.1f}" cy="{y(speedup):.1f}" r="5" fill="#087830"/>'
        f'<text x="{x(slot):.1f}" y="{height - 34}" text-anchor="middle">{slot}</text>'
        f'<text x="{x(slot):.1f}" y="{y(speedup) - 10:.1f}" text-anchor="middle">'
        f"{speedup:.2f}x</text>"
        for slot, speedup in cells
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        "<style>text{font:14px system-ui,sans-serif;fill:#222}</style>"
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#555"/>'
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" stroke="#555"/>'
        f'<polyline points="{points}" fill="none" stroke="#087830" stroke-width="3"/>'
        f"{labels}"
        f'<text x="{width / 2}" y="{height - 8}" text-anchor="middle">Root slots</text>'
        f'<text x="18" y="{height / 2}" transform="rotate(-90 18 {height / 2})" '
        'text-anchor="middle">Speedup vs one slot</text>'
        '<text x="360" y="22" text-anchor="middle" font-weight="bold">'
        "FirstGreen scripted strong scaling</text></svg>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg, encoding="utf-8")
    return path


async def run_scaling_matrix(
    manifest: Manifest,
    *,
    frozen_manifest_path: Path,
    state_root: Path,
    journal_path: Path,
    slots: tuple[int, ...],
    repetitions: int = 1,
    scale_verifier_slots: bool = True,
) -> list[dict[str, Any]]:
    """Replay one immutable task graph; only root/thread/verifier capacities may change."""

    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not slots or any(slot < 1 for slot in slots):
        raise ValueError("slots must contain positive capacities")
    frozen_bytes = frozen_manifest_path.read_bytes()
    frozen_hash = hashlib.sha256(frozen_bytes).hexdigest()
    persisted = Manifest.model_validate(yaml.safe_load(frozen_bytes)).model_dump(mode="json")
    if persisted != manifest.model_dump(mode="json"):
        raise ValueError("frozen manifest bytes do not match the supplied manifest")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    baseline: float | None = None
    source_repo = manifest.project.repo.expanduser().resolve()
    base_sha = subprocess.run(
        ["git", "-C", str(source_repo), "rev-parse", f"{manifest.project.base_ref}^{{commit}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for slot in slots:
        for repetition in range(1, repetitions + 1):
            cell_state = state_root / f"slots-{slot}" / f"repeat-{repetition}"
            execution_repo = cell_state / "repository"
            execution_repo.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", "--quiet", "--no-local", str(source_repo), str(execution_repo)],
                check=True,
                capture_output=True,
            )
            concurrency = manifest.scheduler.concurrency.model_copy(
                update={
                    "mode": "static",
                    "min_root": 1,
                    "max_root": slot,
                    "initial_root": slot,
                    "total_agent_thread_budget": max(
                        slot, slot * (1 + manifest.agent_defaults.max_subagent_threads)
                    ),
                    "verifier_slots": (
                        slot
                        if scale_verifier_slots
                        else manifest.scheduler.concurrency.verifier_slots
                    ),
                }
            )
            cell_manifest = manifest.model_copy(
                update={
                    "project": manifest.project.model_copy(
                        update={"repo": execution_repo, "base_ref": base_sha}
                    ),
                    "scheduler": manifest.scheduler.model_copy(update={"concurrency": concurrency}),
                }
            )
            cell_manifest_path = cell_state / "manifest.yaml"
            cell_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            cell_manifest_path.write_text(
                yaml.safe_dump(cell_manifest.model_dump(mode="json"), sort_keys=False),
                encoding="utf-8",
            )
            started = time.monotonic()
            outcome = await SchedulerService(cell_state).run(
                cell_manifest, cell_manifest_path, "single"
            )
            wall = time.monotonic() - started
            runtime = runtime_observability(SchedulerService(cell_state).repository, outcome.run_id)
            if slot == 1 and baseline is None:
                baseline = wall
            result = {
                "schema_version": "scaling-cell-v1",
                "frozen_manifest_sha256": frozen_hash,
                "slots": slot,
                "repetition": repetition,
                "run_id": outcome.run_id,
                "wall_seconds": wall,
                "speedup_vs_first_one_slot": baseline / wall if baseline is not None else None,
                "efficiency_vs_first_one_slot": (
                    baseline / wall / slot if baseline is not None else None
                ),
                "verified": outcome.verified,
                "failed": outcome.failed,
                "runtime": runtime,
            }
            with journal_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(result, sort_keys=True) + "\n")
            results.append(result)
    return results
