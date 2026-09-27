"""Shared data structures passed between tools, agents, and the orchestrator.

Plain dataclasses (no pydantic/pandas) so the whole project runs on the
standard library only. Every dataclass has a to_dict() used for JSON run
logs and for rendering CLI output.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Literal, Union

ScenarioType = Literal["none", "demand_spike", "capacity_reduction"]

ALL_SKUS = "ALL"


@dataclass
class Scenario:
    type: ScenarioType = "none"
    target_sku: Optional[str] = None
    pct_change: Optional[float] = None  # e.g. 0.20 for +20%, -0.15 for -15%
    target_plant: Optional[str] = None
    target_line: Optional[str] = None
    capacity_reduction_pct: Optional[float] = None  # 1.0 = fully down

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskSpec:
    """Structured request produced by the NL parser."""

    horizon_days: int
    sku_scope: Union[list, str]  # list[str] of SKU ids, or ALL_SKUS
    scenario: Scenario
    raw_text: str
    injection_flagged: bool = False  # phrasing resembling a prompt injection was seen (audit only)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class ParseError:
    """Returned by the NL parser instead of a TaskSpec when the request
    can't be safely or confidently turned into one."""

    reason: str  # short machine tag, e.g. "out_of_scope", "unknown_sku"
    message: str  # human-readable explanation shown to the user

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ForecastRow:
    sku_id: str
    horizon_days: int
    forecast_units: Optional[float]  # None if insufficient data
    method: str  # "exponential_smoothing" | "linear_trend" | "insufficient_data"
    confidence: str  # "High" | "Medium" | "Low" | "None"
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ForecastResult:
    rows: list  # list[ForecastRow]
    warnings: list = field(default_factory=list)

    def by_sku(self) -> dict:
        return {r.sku_id: r for r in self.rows}

    def to_dict(self) -> dict:
        return {"rows": [r.to_dict() for r in self.rows], "warnings": self.warnings}


@dataclass
class LineCapacityRow:
    plant_id: str
    line_id: str
    compatible_skus: frozenset
    daily_capacity: float
    horizon_days: int
    available_capacity: float  # after scenario reduction, over the horizon

    @property
    def key(self):
        return (self.plant_id, self.line_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["compatible_skus"] = sorted(self.compatible_skus)
        return d


@dataclass
class CapacityCheckResult:
    lines: list  # list[LineCapacityRow]
    total_demand: float
    total_capacity: float
    conflict: bool
    structural_shortfall_skus: list  # SKUs whose compatible lines can't ever cover their demand
    rationale: str

    def to_dict(self) -> dict:
        return {
            "lines": [l.to_dict() for l in self.lines],
            "total_demand": self.total_demand,
            "total_capacity": self.total_capacity,
            "conflict": self.conflict,
            "structural_shortfall_skus": self.structural_shortfall_skus,
            "rationale": self.rationale,
        }


@dataclass
class AllocationRow:
    sku_id: str
    plant_id: str
    line_id: str
    allocated_units: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AllocationResult:
    allocations: list  # list[AllocationRow]
    shortfall: dict  # sku_id -> unmet units
    unforecastable: list  # sku_ids that had no usable forecast, not allocated
    rationale: str

    def to_dict(self) -> dict:
        return {
            "allocations": [a.to_dict() for a in self.allocations],
            "shortfall": self.shortfall,
            "unforecastable": self.unforecastable,
            "rationale": self.rationale,
        }


@dataclass
class OrchestratorResult:
    """Final assembled result of a single user request."""

    refused: bool
    refusal_reason: Optional[str] = None
    task_spec: Optional[TaskSpec] = None
    forecast: Optional[ForecastResult] = None
    capacity: Optional[CapacityCheckResult] = None
    allocation: Optional[AllocationResult] = None
    degraded_notes: list = field(default_factory=list)
    retries: dict = field(default_factory=dict)  # e.g. {"forecasting": 0, "capacity": 0, "allocation": 0}

    def to_dict(self) -> dict:
        return {
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "task_spec": self.task_spec.to_dict() if self.task_spec else None,
            "forecast": self.forecast.to_dict() if self.forecast else None,
            "capacity": self.capacity.to_dict() if self.capacity else None,
            "allocation": self.allocation.to_dict() if self.allocation else None,
            "degraded_notes": self.degraded_notes,
            "retries": self.retries,
        }


@dataclass
class AgentOutcome:
    """Wraps any sub-agent call for the orchestrator's retry/validation loop."""

    success: bool
    data: object
    error: Optional[str]
    retries: int

    def to_dict(self) -> dict:
        data = self.data
        if hasattr(data, "to_dict"):
            data = data.to_dict()
        return {"success": self.success, "data": data, "error": self.error, "retries": self.retries}
