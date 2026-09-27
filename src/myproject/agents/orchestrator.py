"""Orchestrator: parses the request, then sequences the three specialist
agents (forecast -> reconcile -> allocate), validating and retrying each
before moving on. Degrades gracefully (partial results + a clear "could
not complete X" note) if a sub-agent still fails after its retries, and
hard-stops once the 10-invocation-per-request budget is spent.

See .claude/skills/request-orchestration/SKILL.md.
"""

from __future__ import annotations

from myproject import logging_utils
from myproject.budget import InvocationBudget
from myproject.schemas import ParseError, OrchestratorResult
from myproject.tools import nl_parser_tool
from myproject.agents import forecasting_agent, capacity_agent, allocation_agent

MAX_INVOCATIONS_PER_REQUEST = 10


def handle_request(raw_text: str, data_dir: str, logs_dir: str, on_stage=None) -> tuple:
    """Returns (OrchestratorResult, run_id).

    `on_stage`, if given, is called with one of "parsing", "forecasting",
    "capacity", "allocation" right before that step runs - purely so a UI
    can show real per-stage progress off the actual pipeline sequencing,
    without re-implementing any of the sequencing/retry/budget logic
    itself. It has no effect on behavior."""

    def _notify(stage: str) -> None:
        if on_stage is not None:
            on_stage(stage)

    run_id = logging_utils.new_run_id()
    run_logger = logging_utils.RunLogger(logs_dir, run_id)
    budget = InvocationBudget(max_invocations=MAX_INVOCATIONS_PER_REQUEST)
    retries = {}

    budget.consume()  # parsing counts as the first invocation of the request
    _notify("parsing")
    parsed = nl_parser_tool.parse_request(raw_text, data_dir)

    if isinstance(parsed, ParseError):
        run_logger.log(
            agent="nl_parser",
            input_summary={"raw_text": raw_text},
            output_summary=parsed.to_dict(),
            retries=0,
            passed=False,
            note=parsed.reason,
        )
        return OrchestratorResult(refused=True, refusal_reason=parsed.message), run_id

    task_spec = parsed
    run_logger.log(
        agent="nl_parser",
        input_summary={"raw_text": raw_text},
        output_summary=task_spec.to_dict(),
        retries=0,
        passed=True,
        note="prompt_injection_phrasing_detected_and_ignored" if task_spec.injection_flagged else "",
    )

    degraded_notes = []

    _notify("forecasting")
    forecast_outcome = forecasting_agent.run(task_spec, data_dir, run_logger, budget)
    retries["forecasting"] = forecast_outcome.retries
    if not forecast_outcome.success:
        degraded_notes.append(f"Could not complete demand forecasting: {forecast_outcome.error}")
        return OrchestratorResult(refused=False, task_spec=task_spec, degraded_notes=degraded_notes, retries=retries), run_id
    forecast_result = forecast_outcome.data

    _notify("capacity")
    capacity_outcome = capacity_agent.run(forecast_result, task_spec, data_dir, run_logger, budget)
    retries["capacity"] = capacity_outcome.retries
    if not capacity_outcome.success:
        degraded_notes.append(f"Could not complete capacity reconciliation: {capacity_outcome.error}")
        return OrchestratorResult(
            refused=False, task_spec=task_spec, forecast=forecast_result, degraded_notes=degraded_notes, retries=retries
        ), run_id
    capacity_result = capacity_outcome.data

    _notify("allocation")
    allocation_outcome = allocation_agent.run(forecast_result, capacity_result, data_dir, run_logger, budget)
    retries["allocation"] = allocation_outcome.retries
    if not allocation_outcome.success:
        degraded_notes.append(f"Could not complete allocation planning: {allocation_outcome.error}")
        return OrchestratorResult(
            refused=False,
            task_spec=task_spec,
            forecast=forecast_result,
            capacity=capacity_result,
            degraded_notes=degraded_notes,
            retries=retries,
        ), run_id
    allocation_result = allocation_outcome.data

    return OrchestratorResult(
        refused=False,
        task_spec=task_spec,
        forecast=forecast_result,
        capacity=capacity_result,
        allocation=allocation_result,
        degraded_notes=degraded_notes,
        retries=retries,
    ), run_id
