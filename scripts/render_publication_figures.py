"""Render publication SVGs from a frozen FirstGreen scaling journal."""

from __future__ import annotations

import argparse
import html
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_rows(path: Path) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            grouped[int(row["slots"])].append(row)
    if sorted(grouped) != [1, 2, 4, 8]:
        raise ValueError("expected frozen slots 1, 2, 4, and 8")
    if any(len(rows) != 2 for rows in grouped.values()):
        raise ValueError("expected exactly two repetitions per slot")
    return dict(grouped)


def _line(points: list[tuple[float, float]], *, color: str, dashed: bool = False) -> str:
    coordinates = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dash = ' stroke-dasharray="8 6"' if dashed else ""
    return f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"{dash}/>'


def _circle(x: float, y: float, *, color: str, label: str, label_offset: float) -> str:
    anchor_y = y + label_offset
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>'
        f'<text x="{x:.1f}" y="{anchor_y:.1f}" text-anchor="middle" '
        f'class="point-label">{label}</text>'
    )


def _base_svg(*, title: str, description: str, body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560"
  viewBox="0 0 960 560" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">{description}</desc>
  <rect width="960" height="560" fill="#ffffff"/>
  <style>
    text {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; fill: #17202a; }}
    .title {{ font-size: 24px; font-weight: 600; }}
    .subtitle {{ font-size: 14px; fill: #52606d; }}
    .axis {{ font-size: 13px; fill: #52606d; }}
    .point-label {{ font-size: 12px; font-weight: 600; }}
    .annotation {{ font-size: 13px; fill: #34495e; }}
  </style>
{body}
</svg>
"""


def render_scaling(grouped: dict[int, list[dict[str, Any]]]) -> str:
    slots = [1, 2, 4, 8]
    x_by_slot = {slot: 120 + index * 240 for index, slot in enumerate(slots)}
    top, bottom, maximum = 92.0, 456.0, 600.0

    def y(value: float) -> float:
        return bottom - value / maximum * (bottom - top)

    elements = [
        '<text x="64" y="38" class="title">Controlled-live Luna strong scaling</text>',
        '<text x="64" y="62" class="subtitle">Frozen Ramsey DAG · 5 tasks · '
        "ready width 4 · all 8 cells verified</text>",
        '<rect x="720" y="82" width="184" height="374" fill="#f3f6f8"/>',
        '<text x="812" y="106" text-anchor="middle" class="annotation">overprovisioned</text>',
    ]
    for tick in (0, 150, 300, 450, 600):
        tick_y = y(float(tick))
        elements.append(
            f'<line x1="72" y1="{tick_y:.1f}" x2="904" y2="{tick_y:.1f}" '
            'stroke="#d9e0e6" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="60" y="{tick_y + 5:.1f}" text-anchor="end" class="axis">{tick}</text>'
        )
    elements.extend(
        [
            '<line x1="72" y1="92" x2="72" y2="456" stroke="#697782" stroke-width="1.5"/>',
            '<line x1="72" y1="456" x2="904" y2="456" stroke="#697782" stroke-width="1.5"/>',
            '<text x="20" y="274" transform="rotate(-90 20 274)" '
            'text-anchor="middle" class="axis">Wall time (seconds)</text>',
            '<text x="488" y="522" text-anchor="middle" class="axis">Root slots</text>',
        ]
    )
    for slot in slots:
        x = x_by_slot[slot]
        elements.append(f'<text x="{x}" y="486" text-anchor="middle" class="axis">{slot}</text>')

    colors = ("#2563eb", "#d97706")
    for repetition in (0, 1):
        points = [
            (float(x_by_slot[slot]), y(float(grouped[slot][repetition]["wall_seconds"])))
            for slot in slots
        ]
        elements.append(_line(points, color=colors[repetition]))
        for slot, (x, point_y) in zip(slots, points, strict=True):
            wall = float(grouped[slot][repetition]["wall_seconds"])
            offset = -12.0 if repetition == 0 else 22.0
            if slot == 4:
                offset = 26.0 if repetition == 0 else -16.0
            elements.append(
                _circle(
                    x,
                    point_y,
                    color=colors[repetition],
                    label=f"R{repetition + 1} {wall:.0f}",
                    label_offset=offset,
                )
            )

    medians = [
        statistics.median(float(row["wall_seconds"]) for row in grouped[slot]) for slot in slots
    ]
    median_points = [
        (float(x_by_slot[slot]), y(value)) for slot, value in zip(slots, medians, strict=True)
    ]
    elements.append(_line(median_points, color="#16794b", dashed=True))
    for slot, (x, point_y), value in zip(slots, median_points, medians, strict=True):
        elements.append(
            f'<rect x="{x - 5:.1f}" y="{point_y - 5:.1f}" width="10" height="10" '
            'fill="#16794b" transform="rotate(45 '
            f'{x:.1f} {point_y:.1f})"/>'
        )
        if slot in (4, 8):
            label_x = x + 14 if slot == 4 else x - 14
            anchor = "start" if slot == 4 else "end"
            box_x = label_x - 5 if slot == 4 else label_x - 62
            elements.append(
                f'<rect x="{box_x:.1f}" y="{point_y - 9:.1f}" width="67" height="18" '
                'fill="#ffffff" fill-opacity="0.9"/>'
                f'<text x="{label_x:.1f}" y="{point_y + 5:.1f}" text-anchor="{anchor}" '
                f'class="point-label">M {value:.1f}</text>'
            )
    elements.extend(
        [
            '<line x1="82" y1="538" x2="110" y2="538" stroke="#2563eb" stroke-width="3"/>',
            '<text x="118" y="543" class="axis">repeat 1</text>',
            '<line x1="206" y1="538" x2="234" y2="538" stroke="#d97706" stroke-width="3"/>',
            '<text x="242" y="543" class="axis">repeat 2</text>',
            '<line x1="330" y1="538" x2="358" y2="538" stroke="#16794b" '
            'stroke-width="3" stroke-dasharray="8 6"/>',
            '<text x="366" y="543" class="axis">median</text>',
            '<text x="904" y="543" text-anchor="end" class="subtitle">'
            "gpt-5.6-luna · low reasoning · 2026-08-18</text>",
        ]
    )
    return _base_svg(
        title="Controlled-live Luna strong scaling",
        description=(
            "Two raw repetitions and their median at one, two, four, and eight root slots. "
            "Median wall time falls through four slots and is flat from four to eight slots."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def render_efficiency(grouped: dict[int, list[dict[str, Any]]]) -> str:
    slots = [1, 2, 4, 8]
    x_by_slot = {slot: 130 + index * 240 for index, slot in enumerate(slots)}
    top, bottom = 108.0, 452.0

    def y(value: float) -> float:
        return bottom - value * (bottom - top)

    elements = [
        '<text x="64" y="38" class="title">Useful capacity saturates after four slots</text>',
        '<text x="64" y="62" class="subtitle">'
        "Root-slot utilization from persisted attempt intervals</text>",
        '<rect x="730" y="82" width="174" height="370" fill="#f3f6f8"/>',
    ]
    for percent in (0, 25, 50, 75, 100):
        tick_y = y(percent / 100)
        elements.append(
            f'<line x1="72" y1="{tick_y:.1f}" x2="904" y2="{tick_y:.1f}" '
            'stroke="#d9e0e6" stroke-width="1"/>'
        )
        elements.append(
            f'<text x="60" y="{tick_y + 5:.1f}" text-anchor="end" class="axis">{percent}%</text>'
        )
    elements.extend(
        [
            '<line x1="72" y1="108" x2="72" y2="452" stroke="#697782" stroke-width="1.5"/>',
            '<line x1="72" y1="452" x2="904" y2="452" stroke="#697782" stroke-width="1.5"/>',
            '<text x="488" y="518" text-anchor="middle" class="axis">Root slots</text>',
        ]
    )
    for slot in slots:
        rows = grouped[slot]
        values = [float(row["runtime"]["root_slot_utilization"]) for row in rows]
        x = float(x_by_slot[slot])
        low, high = min(values), max(values)
        median = statistics.median(values)
        elements.extend(
            [
                f'<line x1="{x:.1f}" y1="{y(high):.1f}" x2="{x:.1f}" '
                f'y2="{y(low):.1f}" stroke="#2563eb" stroke-width="5" '
                'stroke-linecap="round"/>',
                f'<circle cx="{x:.1f}" cy="{y(values[0]):.1f}" r="7" fill="#2563eb"/>',
                f'<circle cx="{x:.1f}" cy="{y(values[1]):.1f}" r="7" '
                'fill="#ffffff" stroke="#2563eb" stroke-width="3"/>',
                f'<text x="{x:.1f}" y="{y(median) - 18:.1f}" '
                f'text-anchor="middle" class="point-label">{median * 100:.1f}%</text>',
                f'<text x="{x:.1f}" y="482" text-anchor="middle" class="axis">{slot}</text>',
            ]
        )
    elements.extend(
        [
            '<text x="904" y="96" text-anchor="end" class="annotation">ready width = 4</text>',
            '<text x="904" y="542" text-anchor="end" class="subtitle">'
            "8-slot utilization ≈ half of 4-slot utilization</text>",
        ]
    )
    return _base_svg(
        title="Root-slot utilization by configured capacity",
        description=(
            "Two repetitions per slot. Utilization is about 58 percent at four slots and "
            "29 percent at eight slots because the frozen graph exposes only four root tasks."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def render_javascript_timeline(trace: dict[str, Any]) -> str:
    metadata = trace.get("metadata", {})
    makespan = float(metadata["makespan_seconds"])
    events = [
        event
        for event in trace.get("traceEvents", [])
        if event.get("ph") == "X" and event.get("cat") in {"agent", "integration"}
    ]
    if not events or makespan <= 0:
        raise ValueError("JavaScript trace has no complete attempt intervals")

    lane_by_task = {
        "checkout-documentation": ("Documentation", 150.0),
        "core-idempotent-checkout": ("Core", 245.0),
        "idempotent-checkout-tests": ("Tests", 340.0),
        "final delivery": ("Delivery", 435.0),
    }
    left, right = 210.0, 910.0

    def x(seconds: float) -> float:
        return left + seconds / makespan * (right - left)

    repaired_tasks = {
        str(event.get("args", {}).get("task_key"))
        for event in events
        if event.get("args", {}).get("role") == "repair"
    }
    elements = [
        '<text x="64" y="38" class="title">Independent JavaScript case: verified timeline</text>',
        '<text x="64" y="62" class="subtitle">'
        "Two roots start together; two primaries are rejected; delivery verifies at 289.1 s"
        "</text>",
    ]
    for label, lane_y in lane_by_task.values():
        elements.extend(
            [
                f'<text x="190" y="{lane_y + 5:.1f}" text-anchor="end" class="axis">{label}</text>',
                f'<line x1="{left:.1f}" y1="{lane_y:.1f}" x2="{right:.1f}" '
                f'y2="{lane_y:.1f}" stroke="#d9e0e6" stroke-width="1"/>',
            ]
        )

    for tick in (0, 60, 120, 180, 240, round(makespan)):
        tick_x = x(float(tick))
        elements.extend(
            [
                f'<line x1="{tick_x:.1f}" y1="112" x2="{tick_x:.1f}" y2="468" '
                'stroke="#e3e8ed" stroke-width="1"/>',
                f'<text x="{tick_x:.1f}" y="500" text-anchor="middle" class="axis">{tick}</text>',
            ]
        )
    elements.append(
        '<text x="560" y="532" text-anchor="middle" class="axis">Seconds from run start</text>'
    )

    core_verified_at: float | None = None
    for event in events:
        category = str(event.get("cat"))
        args = event.get("args", {})
        task_key = "final delivery" if category == "integration" else str(args.get("task_key", ""))
        if task_key not in lane_by_task:
            continue
        _, lane_y = lane_by_task[task_key]
        started = float(event["ts"]) / 1_000_000
        duration = float(event["dur"]) / 1_000_000
        bar_x = x(started)
        bar_width = max(8.0, x(started + duration) - bar_x)
        role = str(args.get("role", "verification"))
        rejected = role == "primary" and task_key in repaired_tasks
        if category == "integration":
            fill, label = "#16794b", "verify ✓"
        elif rejected:
            fill, label = "#b42318", "primary ×"
        elif role == "repair":
            fill, label = "#d97706", "repair ✓"
            if task_key == "core-idempotent-checkout":
                core_verified_at = started + duration
        else:
            fill, label = "#2563eb", "primary ✓"
        elements.append(
            f'<rect x="{bar_x:.1f}" y="{lane_y - 20:.1f}" width="{bar_width:.1f}" '
            f'height="40" rx="5" fill="{fill}"/>'
        )
        if bar_width >= 72:
            elements.append(
                f'<text x="{bar_x + bar_width / 2:.1f}" y="{lane_y + 5:.1f}" '
                'text-anchor="middle" style="font-size:12px;fill:#ffffff;font-weight:600">'
                f"{html.escape(label)} · {duration:.1f}s</text>"
            )
        else:
            elements.append(
                f'<text x="{bar_x - 6:.1f}" y="{lane_y + 5:.1f}" text-anchor="end" '
                f'class="point-label">{html.escape(label)}</text>'
            )

    if core_verified_at is not None:
        release_x = x(core_verified_at)
        elements.extend(
            [
                f'<line x1="{release_x:.1f}" y1="273" x2="{release_x:.1f}" y2="315" '
                'stroke="#34495e" stroke-width="2" marker-end="url(#arrow)"/>',
                f'<text x="{release_x + 8:.1f}" y="292" class="annotation">'
                "core verified → tests released</text>",
            ]
        )
    elements.insert(
        0,
        '  <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="5" refY="3" '
        'orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#34495e"/></marker></defs>',
    )
    return _base_svg(
        title="Independent JavaScript controlled-live timeline",
        description=(
            "Documentation and core implementation start together. The core primary fails, a "
            "repair verifies, tests are released, their primary fails, their repair verifies, "
            "and final delivery passes at 289.1 seconds."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def render_critical_path_ablation(
    summary: dict[str, Any],
    stable_trace: dict[str, Any],
    critical_trace: dict[str, Any],
) -> str:
    """Render representative two-slot timelines for the ready-queue ablation."""

    stable_median = float(summary["stable"]["median_wall_seconds"])
    critical_median = float(summary["critical_path"]["median_wall_seconds"])
    reduction = float(summary["median_wall_reduction_percent"])
    maximum = max(
        float(stable_trace["metadata"]["makespan_seconds"]),
        float(critical_trace["metadata"]["makespan_seconds"]),
    )
    left, right = 210.0, 910.0

    def x(seconds: float) -> float:
        return left + seconds / maximum * (right - left)

    task_style = {
        "side-a": ("side A", "#2563eb"),
        "side-b": ("side B", "#7c3aed"),
        "z-critical-1": ("critical 1", "#b42318"),
        "z-critical-2": ("critical 2", "#d97706"),
        "join": ("join", "#16794b"),
        "final delivery": ("delivery", "#34495e"),
    }
    elements = [
        '<text x="64" y="38" class="title">Critical-path ranking advances the long chain</text>',
        '<text x="64" y="62" class="subtitle">'
        f"Three runs per policy · median wall {stable_median:.3f}s → "
        f"{critical_median:.3f}s ({reduction:.2f}% lower)</text>",
    ]

    for tick in range(0, 10, 2):
        tick_x = x(float(tick))
        elements.extend(
            [
                f'<line x1="{tick_x:.1f}" y1="102" x2="{tick_x:.1f}" y2="472" '
                'stroke="#e3e8ed" stroke-width="1"/>',
                f'<text x="{tick_x:.1f}" y="96" text-anchor="middle" class="axis">{tick}</text>',
            ]
        )
    elements.append('<text x="910" y="96" text-anchor="end" class="axis">seconds</text>')

    def add_panel(trace: dict[str, Any], *, label: str, lane_y: tuple[float, float, float]) -> None:
        elements.append(
            f'<text x="190" y="{lane_y[0] - 26:.1f}" text-anchor="end" '
            f'class="point-label">{html.escape(label)}</text>'
        )
        for lane in lane_y:
            elements.append(
                f'<line x1="{left:.1f}" y1="{lane:.1f}" x2="{right:.1f}" y2="{lane:.1f}" '
                'stroke="#d9e0e6" stroke-width="1"/>'
            )
        agent_available = [0.0, 0.0]
        events = [
            event
            for event in trace["traceEvents"]
            if event.get("ph") == "X" and event.get("cat") in {"agent", "integration"}
        ]
        for event in sorted(events, key=lambda item: float(item["ts"])):
            started = float(event["ts"]) / 1_000_000
            duration = float(event["dur"]) / 1_000_000
            if event.get("cat") == "integration":
                task_key = "final delivery"
                lane = lane_y[2]
            else:
                task_key = str(event.get("args", {}).get("task_key"))
                available_lanes = [
                    index
                    for index, available_at in enumerate(agent_available)
                    if available_at <= started
                ]
                lane_index = (
                    available_lanes[0]
                    if available_lanes
                    else min(range(2), key=lambda index: agent_available[index])
                )
                agent_available[lane_index] = started + duration
                lane = lane_y[lane_index]
            task_label, fill = task_style[task_key]
            bar_x = x(started)
            bar_width = max(8.0, x(started + duration) - bar_x)
            elements.append(
                f'<rect x="{bar_x:.1f}" y="{lane - 16:.1f}" width="{bar_width:.1f}" '
                f'height="32" rx="5" fill="{fill}"/>'
            )
            if bar_width >= 58:
                elements.append(
                    f'<text x="{bar_x + bar_width / 2:.1f}" y="{lane + 4:.1f}" '
                    'text-anchor="middle" '
                    'style="font-size:11px;fill:#ffffff;font-weight:600">'
                    f"{html.escape(task_label)}</text>"
                )

    add_panel(stable_trace, label="Stable", lane_y=(150.0, 195.0, 240.0))
    elements.append('<line x1="64" y1="286" x2="920" y2="286" stroke="#aeb8c2" stroke-width="1"/>')
    add_panel(critical_trace, label="Critical path", lane_y=(350.0, 395.0, 440.0))
    return _base_svg(
        title="Stable versus critical-path ready-queue scheduling",
        description=(
            "Representative median traces show stable ordering consuming the first two slots "
            "with side branches, while critical-path ordering starts the dependent long chain."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def render_ramsey_trace(trace: dict[str, Any]) -> str:
    """Render one sanitized four-slot Ramsey branch/join trace."""

    makespan = float(trace["metadata"]["makespan_seconds"])
    left, right = 220.0, 910.0

    def x(seconds: float) -> float:
        return left + seconds / makespan * (right - left)

    lanes = {
        "ramsey-shard-0": ("Shard 0", 135.0, "#2563eb"),
        "ramsey-shard-1": ("Shard 1", 190.0, "#3b82f6"),
        "ramsey-shard-2": ("Shard 2", 245.0, "#60a5fa"),
        "ramsey-shard-3": ("Shard 3", 300.0, "#7c3aed"),
        "ramsey-certificate": ("Certificate join", 385.0, "#d97706"),
        "final delivery": ("Delivery", 455.0, "#16794b"),
    }
    elements = [
        '<defs><marker id="ramsey-arrow" markerWidth="8" markerHeight="8" refX="5" '
        'refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#34495e"/>'
        "</marker></defs>",
        '<text x="64" y="38" class="title">Four-slot Ramsey trace: width ends at the join</text>',
        '<text x="64" y="62" class="subtitle">'
        "All four roots start together; the certificate waits for the slowest verified shard"
        "</text>",
    ]
    for tick in (0, 35, 70, 105, 140):
        tick_x = x(min(float(tick), makespan))
        tick_label = f"{tick} s" if tick == 140 else str(tick)
        tick_anchor = "end" if tick == 140 else "middle"
        elements.extend(
            [
                f'<line x1="{tick_x:.1f}" y1="92" x2="{tick_x:.1f}" y2="482" '
                'stroke="#e3e8ed" stroke-width="1"/>',
                f'<text x="{tick_x:.1f}" y="86" text-anchor="{tick_anchor}" '
                f'class="axis">{tick_label}</text>',
            ]
        )
    for task_label, lane_y, _ in lanes.values():
        elements.extend(
            [
                f'<text x="200" y="{lane_y + 5:.1f}" text-anchor="end" '
                f'class="axis">{task_label}</text>',
                f'<line x1="{left:.1f}" y1="{lane_y:.1f}" x2="{right:.1f}" y2="{lane_y:.1f}" '
                'stroke="#d9e0e6" stroke-width="1"/>',
            ]
        )

    join_started: float | None = None
    for event in trace["traceEvents"]:
        if event.get("ph") != "X" or event.get("cat") not in {"agent", "integration"}:
            continue
        task_key = (
            "final delivery"
            if event.get("cat") == "integration"
            else str(event.get("args", {}).get("task_key"))
        )
        task_label, lane_y, fill = lanes[task_key]
        bar_label = "verify" if task_key == "final delivery" else task_label
        started = float(event["ts"]) / 1_000_000
        duration = float(event["dur"]) / 1_000_000
        if task_key == "ramsey-certificate":
            join_started = started
        bar_x = x(started)
        bar_width = max(8.0, x(started + duration) - bar_x)
        elements.append(
            f'<rect x="{bar_x:.1f}" y="{lane_y - 18:.1f}" width="{bar_width:.1f}" '
            f'height="36" rx="5" fill="{fill}"/>'
        )
        if bar_width >= 74:
            elements.append(
                f'<text x="{bar_x + bar_width / 2:.1f}" y="{lane_y + 5:.1f}" '
                'text-anchor="middle" style="font-size:12px;fill:#ffffff;font-weight:600">'
                f"{html.escape(bar_label)} · {duration:.1f}s</text>"
            )
        else:
            elements.append(
                f'<text x="{bar_x - 6:.1f}" y="{lane_y + 5:.1f}" text-anchor="end" '
                f'class="point-label">{html.escape(bar_label)}</text>'
            )
    if join_started is not None:
        release_x = x(join_started)
        elements.extend(
            [
                f'<line x1="{release_x:.1f}" y1="322" x2="{release_x:.1f}" y2="355" '
                'stroke="#34495e" stroke-width="2" marker-end="url(#ramsey-arrow)"/>',
                f'<text x="{release_x + 8:.1f}" y="342" class="annotation">'
                "slowest shard verified → join released</text>",
            ]
        )
    return _base_svg(
        title="Representative four-slot Ramsey branch/join trace",
        description=(
            "Four shard attempts overlap from run start. A certificate task begins only after "
            "all shards verify, followed by final delivery verification."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def render_system_overview() -> str:
    """Render the product path with evidence as a downstream consumer."""

    elements = [
        '<defs><marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="5" refY="3" '
        'orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#34495e"/></marker></defs>',
        '<text x="64" y="40" class="title">'
        "FirstGreen treats a software goal as a parallel program</text>",
        '<text x="64" y="66" class="subtitle">'
        "Extraction exposes safe work; scheduling converts it into shorter verified makespan"
        "</text>",
    ]
    boxes = [
        (64, 112, 220, 104, "Repository + goal", "read-only bounded input", "#e8f0fe"),
        (370, 112, 220, 104, "Parallelism extraction", "semantic units + path audit", "#e8f0fe"),
        (676, 112, 220, 104, "Approved DAG", "work · span · conflicts", "#fff3e0"),
        (370, 280, 220, 90, "Agent scheduling", "critical path · slots · locks", "#ede9fe"),
        (676, 280, 220, 90, "Verified delivery", "winner + composed final gate", "#e7f6ed"),
        (64, 380, 220, 70, "Evidence bundle", "raw rows · traces · report", "#f3f6f8"),
    ]
    for box_x, box_y, box_w, box_h, heading, detail, fill in boxes:
        elements.extend(
            [
                f'<rect x="{box_x}" y="{box_y}" width="{box_w}" height="{box_h}" rx="10" '
                f'fill="{fill}" stroke="#aeb8c2" stroke-width="1.5"/>',
                f'<text x="{box_x + box_w / 2:.1f}" y="{box_y + box_h * 0.42:.1f}" '
                'text-anchor="middle" '
                f'class="point-label">{heading}</text>',
                f'<text x="{box_x + box_w / 2:.1f}" y="{box_y + box_h * 0.68:.1f}" '
                'text-anchor="middle" '
                f'class="axis">{detail}</text>',
            ]
        )
    arrows = [
        (284, 164, 356, 164, False),
        (590, 164, 662, 164, False),
        (590, 325, 662, 325, False),
    ]
    for x1, y1, x2, y2, dashed in arrows:
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        elements.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#34495e" '
            f'stroke-width="2"{dash} marker-end="url(#flow-arrow)"/>'
        )
    elements.extend(
        [
            '<polyline points="786,216 786,242 480,242 480,268" fill="none" '
            'stroke="#34495e" stroke-width="2" marker-end="url(#flow-arrow)"/>',
            '<polyline points="786,370 786,415 296,415" fill="none" stroke="#34495e" '
            'stroke-width="2" stroke-dasharray="7 6" marker-end="url(#flow-arrow)"/>',
            '<text x="520" y="438" text-anchor="middle" class="annotation">'
            "benchmarking observes the product path</text>",
        ]
    )
    return _base_svg(
        title="FirstGreen product path",
        description=(
            "A repository and goal flow through parallelism extraction, an approved DAG, agent "
            "scheduling, and verified delivery. Evidence is a downstream consumer."
        ),
        body="\n".join(f"  {element}" for element in elements),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_journal", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--js-trace", type=Path)
    parser.add_argument("--ramsey-trace", type=Path)
    parser.add_argument("--ablation-summary", type=Path)
    parser.add_argument("--ablation-stable-trace", type=Path)
    parser.add_argument("--ablation-critical-trace", type=Path)
    args = parser.parse_args()

    grouped = _load_rows(args.raw_journal)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    (args.output_directory / "system-overview.svg").write_text(
        render_system_overview(), encoding="utf-8"
    )
    (args.output_directory / "ramsey-scaling.svg").write_text(
        render_scaling(grouped), encoding="utf-8"
    )
    (args.output_directory / "ramsey-efficiency.svg").write_text(
        render_efficiency(grouped), encoding="utf-8"
    )
    if args.js_trace is not None:
        trace = json.loads(args.js_trace.read_text(encoding="utf-8"))
        (args.output_directory / "javascript-live-timeline.svg").write_text(
            render_javascript_timeline(trace), encoding="utf-8"
        )
    if args.ramsey_trace is not None:
        trace = json.loads(args.ramsey_trace.read_text(encoding="utf-8"))
        (args.output_directory / "ramsey-trace.svg").write_text(
            render_ramsey_trace(trace), encoding="utf-8"
        )
    ablation_inputs = (
        args.ablation_summary,
        args.ablation_stable_trace,
        args.ablation_critical_trace,
    )
    if any(path is not None for path in ablation_inputs):
        if any(path is None for path in ablation_inputs):
            raise ValueError("all three critical-path ablation inputs are required together")
        summary = json.loads(args.ablation_summary.read_text(encoding="utf-8"))
        stable_trace = json.loads(args.ablation_stable_trace.read_text(encoding="utf-8"))
        critical_trace = json.loads(args.ablation_critical_trace.read_text(encoding="utf-8"))
        (args.output_directory / "critical-path-ablation.svg").write_text(
            render_critical_path_ablation(summary, stable_trace, critical_trace),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
