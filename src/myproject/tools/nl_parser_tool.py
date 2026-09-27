"""Natural-language parser tool: turns a free-text request into a TaskSpec,
or a ParseError if it can't be done safely and confidently.

This is a deterministic, regex/keyword based parser rather than a live LLM
call (see the project README for why). That choice is itself a guardrail:
the parser never treats the input text as instructions to follow, only as
a string to pattern-match specific, narrow fields out of (a horizon
phrase, an "SKU-N" token, a percentage near a spike/drop keyword, a
plant/line near a maintenance keyword). Anything else in the text -
including an embedded command like "ignore previous instructions" - has
no code path that acts on it. It's simply text that didn't match a
pattern, so it's dropped. `injection_flagged` still records that such
phrasing was seen, purely for the audit log; it has no effect on parsing.

Output is always coerced into the fixed TaskSpec dataclass (or ParseError)
- there is no "free-form JSON from an LLM" step to validate against a
schema, because there's no LLM call to begin with. The equivalent of that
schema check is: every code path below either returns a well-formed
TaskSpec or a well-formed ParseError; nothing else is possible.

Swap-in point: replace `parse_request`'s body with a real LLM call (the
`langchain`/`langsmith` deps are already in pyproject.toml) that returns
JSON validated against the same TaskSpec fields, for broader phrasing
coverage. Keep the post-parse validation (SKU/plant existence, horizon
range) regardless of how the JSON was produced - that's the part that
actually keeps the system safe.
"""

from __future__ import annotations

import re

from myproject import data_access
from myproject.schemas import TaskSpec, ParseError, Scenario, ALL_SKUS

MAX_TEXT_LENGTH = 2000
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 180
DEFAULT_HORIZON_DAYS = 30

IN_SCOPE_KEYWORDS = [
    "plan", "forecast", "demand", "production", "capacity", "allocat",
    "sku", "plant", "line", "maintenance", "spike", "surge", "month",
    "week", "day", "units", "supply", "shortfall", "output", "schedule",
]
# Word-boundary anchored so e.g. "day" doesn't false-positive match inside
# "today", or "line" inside "online" - \b requires a transition into a
# word character, which a same-word continuation like "o|day" lacks.
IN_SCOPE_KEYWORD_PATTERN = re.compile(r"\b(?:" + "|".join(IN_SCOPE_KEYWORDS) + r")\w*", re.I)

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"system\s+prompt",
    r"reveal\s+your\s+(instructions|prompt)",
    r"you\s+are\s+now\s+",
    r"act\s+as\s+(if|a)\b",
]

SKU_PATTERN = r"SKU[-\s]?(\d+)"
PCT_PATTERN = r"(\d+(?:\.\d+)?)\s*%"
SPIKE_KEYWORDS = r"(spik\w*|surg\w*|increas\w*|jump\w*|grows?|rises?|up\s+by)"
DROP_KEYWORDS = r"(drop\w*|decreas\w*|declin\w*|falls?|reduc\w*|down\s+by)"
CAP_DOWN_KEYWORDS = r"(maintenance|down|offline|closed|out\s+of\s+service|reduced)"
PLANT_PATTERN = r"Plant[-\s]?([A-Za-z])"
LINE_PATTERN = r"Line[-\s]?(\d+)"
REDUCTION_PCT_PATTERN = r"reduced\s+by\s+(\d+(?:\.\d+)?)\s*%"
ALL_SKUS_PHRASE = r"\ball\s+skus?\b|\ball\s+products?\b|\bevery\s+sku\b"

HORIZON_PATTERNS = [
    (r"next\s+(\d+)\s*years?", lambda n: n * 365),
    (r"next\s+(\d+)\s*months?", lambda n: n * 30),
    (r"next\s+(\d+)\s*weeks?", lambda n: n * 7),
    (r"next\s+(\d+)\s*days?", lambda n: n),
    (r"(\d+)\s*[- ]?day\b", lambda n: n),
    (r"(\d+)\s*months?\b", lambda n: n * 30),
    (r"(\d+)\s*weeks?\b", lambda n: n * 7),
    (r"next\s+month\b", lambda n: 30),
    (r"this\s+month\b", lambda n: 30),
    (r"next\s+week\b", lambda n: 7),
]


def _extract_horizon_days(text: str):
    for pattern, convert in HORIZON_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            groups = m.groups()
            n = int(groups[0]) if groups and groups[0] is not None else 0
            return convert(n)
    return None


def _extract_sku_tokens(text: str) -> list:
    found = []
    for m in re.finditer(SKU_PATTERN, text, re.I):
        found.append(f"SKU-{int(m.group(1))}")
    # de-dup, preserve numeric order
    return sorted(set(found), key=lambda s: int(s.split("-")[1]))


def _find_demand_scenario(text: str):
    for keyword_pattern, sign in [(SPIKE_KEYWORDS, 1), (DROP_KEYWORDS, -1)]:
        for m in re.finditer(keyword_pattern, text, re.I):
            start, end = max(0, m.start() - 40), min(len(text), m.end() + 40)
            window = text[start:end]
            pct_m = re.search(PCT_PATTERN, window)
            sku_m = re.search(SKU_PATTERN, window, re.I)
            if pct_m and sku_m:
                pct = (float(pct_m.group(1)) / 100.0) * sign
                sku_id = f"SKU-{int(sku_m.group(1))}"
                return sku_id, pct
    return None, None


def _find_capacity_scenario(text: str):
    for m in re.finditer(CAP_DOWN_KEYWORDS, text, re.I):
        start, end = max(0, m.start() - 50), min(len(text), m.end() + 50)
        window = text[start:end]
        plant_m = re.search(PLANT_PATTERN, window, re.I)
        if not plant_m:
            continue
        plant_id = f"Plant-{plant_m.group(1).upper()}"
        line_m = re.search(LINE_PATTERN, window, re.I)
        line_id = f"Line-{line_m.group(1)}" if line_m else None
        pct_m = re.search(REDUCTION_PCT_PATTERN, window, re.I)
        reduction_pct = (float(pct_m.group(1)) / 100.0) if pct_m else 1.0
        return plant_id, line_id, reduction_pct
    return None, None, None


def parse_request(text, data_dir: str):
    """Returns a TaskSpec on success, or a ParseError on any rejection."""
    if not isinstance(text, str) or not text.strip():
        return ParseError("empty_input", "I didn't receive any request text. Try something like \"give me next month's production plan\".")

    text = text.strip()[:MAX_TEXT_LENGTH]
    lower_text = text.lower()

    injection_flagged = any(re.search(p, lower_text) for p in INJECTION_PATTERNS)

    has_sku_mention = bool(re.search(SKU_PATTERN, text, re.I))
    in_scope = has_sku_mention or bool(IN_SCOPE_KEYWORD_PATTERN.search(text))
    if not in_scope:
        return ParseError(
            "out_of_scope",
            "This system only handles SKU demand forecasting, production capacity checks, "
            "and production allocation planning. Try something like \"give me next month's "
            "production plan\" or \"what if demand for SKU-12 spikes 20%?\".",
        )

    horizon_days = _extract_horizon_days(text)
    if horizon_days is None:
        horizon_days = DEFAULT_HORIZON_DAYS
    if not (MIN_HORIZON_DAYS <= horizon_days <= MAX_HORIZON_DAYS):
        approx_months = round(horizon_days / 30, 1)
        return ParseError(
            "invalid_horizon",
            f"A horizon of {horizon_days} day(s) (~{approx_months} months) is outside the "
            f"supported range of {MIN_HORIZON_DAYS}-{MAX_HORIZON_DAYS} days (up to ~6 months). "
            "Please ask for a shorter horizon.",
        )

    known_skus = data_access.known_sku_ids(data_dir)
    found_skus = _extract_sku_tokens(text)
    unknown_skus = [s for s in found_skus if s not in known_skus]
    if unknown_skus:
        max_num = max(int(s.split("-")[1]) for s in known_skus)
        if len(unknown_skus) == 1:
            skus_desc = f"{unknown_skus[0]} is not a recognized SKU id"
        else:
            skus_desc = f"{', '.join(unknown_skus)} are not recognized SKU ids"
        return ParseError(
            "unknown_sku",
            f"{skus_desc}. Valid SKUs are SKU-1 through SKU-{max_num}.",
        )

    force_all = bool(re.search(ALL_SKUS_PHRASE, text, re.I))
    if force_all or not found_skus:
        sku_scope = ALL_SKUS
    else:
        sku_scope = found_skus

    plant_id, line_id, reduction_pct = _find_capacity_scenario(text)
    if plant_id is not None:
        known_plant_lines = data_access.known_plant_line_ids(data_dir)
        if plant_id not in known_plant_lines:
            return ParseError(
                "unknown_plant",
                f"{plant_id} is not a recognized plant. Please check the plant id.",
            )
        if line_id is not None and (plant_id, line_id) not in known_plant_lines:
            return ParseError(
                "unknown_line",
                f"{line_id} is not a recognized line at {plant_id}. Please check the line id.",
            )
        scenario = Scenario(
            type="capacity_reduction",
            target_plant=plant_id,
            target_line=line_id,
            capacity_reduction_pct=reduction_pct,
        )
    else:
        spike_sku, pct_change = _find_demand_scenario(text)
        if spike_sku is not None:
            scenario = Scenario(type="demand_spike", target_sku=spike_sku, pct_change=pct_change)
        else:
            scenario = Scenario(type="none")

    return TaskSpec(
        horizon_days=horizon_days,
        sku_scope=sku_scope,
        scenario=scenario,
        raw_text=text,
        injection_flagged=injection_flagged,
    )
