"""Transparent delayed-hedge policy with conservative gates."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeBucket:
    repo_fingerprint: str
    task_class: str
    adapter: str
    model: str
    verifier_profile: str

    def fallbacks(self) -> tuple[tuple[str, ...], ...]:
        return (
            (
                self.repo_fingerprint,
                self.task_class,
                self.adapter,
                self.model,
                self.verifier_profile,
            ),
            (self.repo_fingerprint, self.task_class, self.adapter, self.model),
            (self.repo_fingerprint, self.adapter, self.model),
            (self.adapter, self.model),
        )


def empirical_quantile(samples: list[float], quantile: float) -> float:
    if not samples:
        raise ValueError("quantile requires samples")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


@dataclass(frozen=True)
class Threshold:
    seconds: float | None
    source: str
    sample_count: int


def choose_threshold(
    samples_by_bucket: dict[tuple[str, ...], list[float]],
    bucket: RuntimeBucket,
    *,
    quantile: float,
    min_samples: int,
    fallback_seconds: float | None,
) -> Threshold:
    for index, key in enumerate(bucket.fallbacks()):
        samples = samples_by_bucket.get(key, [])
        if len(samples) >= min_samples:
            return Threshold(
                empirical_quantile(samples, quantile), f"historical_level_{index}", len(samples)
            )
    if fallback_seconds is not None:
        return Threshold(fallback_seconds, "configured_fallback", 0)
    return Threshold(None, "unavailable", 0)


@dataclass(frozen=True)
class HedgeInputs:
    replay_safe: bool
    enabled: bool
    winner_absent: bool
    primary_active: bool
    replicas: int
    max_replicas: int
    budget_available: bool
    slots_available: bool
    resources_available: bool
    controller_backoff: bool
    elapsed_seconds: float
    threshold: Threshold
    estimated_extra_cost: float | None = None


@dataclass(frozen=True)
class HedgeDecision:
    launch: bool
    reason: str
    threshold_seconds: float | None
    threshold_source: str
    sample_count: int
    estimated_extra_cost: float | None


class HedgePolicy:
    version = "hedge-v1"

    def evaluate(self, inputs: HedgeInputs) -> HedgeDecision:
        reason = self._blocked_reason(inputs)
        return HedgeDecision(
            reason is None,
            "threshold_reached" if reason is None else reason,
            inputs.threshold.seconds,
            inputs.threshold.source,
            inputs.threshold.sample_count,
            inputs.estimated_extra_cost,
        )

    @staticmethod
    def _blocked_reason(inputs: HedgeInputs) -> str | None:
        if not inputs.replay_safe:
            return "task_not_replay_safe"
        if not inputs.enabled:
            return "hedging_disabled"
        if not inputs.winner_absent:
            return "winner_exists"
        if not inputs.primary_active:
            return "primary_not_active"
        if inputs.replicas >= inputs.max_replicas:
            return "max_replicas_reached"
        if not inputs.budget_available:
            return "hedge_budget_exhausted"
        if not inputs.slots_available:
            return "no_root_slot"
        if not inputs.resources_available:
            return "resource_unavailable"
        if inputs.controller_backoff:
            return "controller_backoff"
        if inputs.threshold.seconds is None:
            return "threshold_unavailable"
        if inputs.elapsed_seconds < inputs.threshold.seconds:
            return "threshold_not_reached"
        return None
