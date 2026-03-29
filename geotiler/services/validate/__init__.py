# geotiler/services/validate/__init__.py
"""
Dataset validation service.

Shared types and helpers for validation check functions.
Each submodule (vector, cog, zarr, stac) exports a single async entry point
that returns a ValidationReport.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Depth(str, Enum):
    """Validation depth level."""
    metadata = "metadata"
    sample = "sample"
    full = "full"


class Status(str, Enum):
    """Check result status. Ordered by severity: pass < warn < fail."""
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


def check(
    name: str,
    status: Status,
    message: str,
    details: Optional[dict[str, Any]] = None,
) -> dict:
    """Build a single check result dict."""
    result = {"name": name, "status": status.value, "message": message}
    if details is not None:
        result["details"] = details
    return result


def report(
    target: str,
    target_type: str,
    depth: Depth,
    checks: list[dict],
) -> dict:
    """Build a validation report from a list of check results."""
    # Overall status is the worst of all checks
    severity = {Status.PASS.value: 0, Status.WARN.value: 1, Status.FAIL.value: 2}
    worst = max(checks, key=lambda c: severity.get(c["status"], 0)) if checks else None
    overall = worst["status"] if worst else Status.PASS.value

    # Summary counts
    counts = {Status.PASS.value: 0, Status.WARN.value: 0, Status.FAIL.value: 0}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    total = len(checks)
    parts = []
    if counts["fail"]:
        parts.append(f"{counts['fail']} fail")
    if counts["warn"]:
        parts.append(f"{counts['warn']} warn")
    if counts["pass"]:
        parts.append(f"{counts['pass']} pass")
    summary = f"{total} checks: {', '.join(parts)}"

    return {
        "target": target,
        "target_type": target_type,
        "depth": depth.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": overall,
        "summary": summary,
        "checks": checks,
    }
