"""Hydrolog's refusals of a computation as Hydrograf's errors, worded in Polish.

Hydrolog checks the inputs of each formula against its spec before it computes (Nogat
CMP-3.1, CMP-3.2) and refuses a value with ``InvalidParameterError``, code
``validation_error``, whose ``details.reason`` is the standard's:
``outside_physical_range`` for a value outside the physical range of an input
(``details.option``, ``value`` and ``range``) or for a broken physical condition
between inputs (``details.constraint`` and its English ``text``), ``invalid_type`` for
a value that is not a number, and ``precondition_failed`` with ``details.constraint``
for a condition of applicability of the formula. :func:`refusal` turns such a refusal
into an ``InvalidRequestError`` (400) of the message catalogue with the same
``reason``, ``formula``, ``constraint`` and ``option``: the conditions Hydrograf's
inputs can break (Lutz's Lc ≤ L and U + W ≤ 100, Kerby–Kirpich's flow path longer
than its overland segment) have Polish sentences of their own, any other is named by
its formula and constraint with Hydrolog's statement of it. Another refusal keeps
Hydrolog's English message as ``invalid_parameters``.
"""

import math
from collections.abc import Mapping
from typing import Any

from hydrolog.exceptions import InvalidParameterError

from core.errors import InvalidRequestError


def refusal(error: InvalidParameterError) -> InvalidRequestError:
    """Return the error of the API for a refusal of Hydrolog.

    Parameters
    ----------
    error : InvalidParameterError
        Hydrolog's refusal of an input of a formula.

    Returns
    -------
    InvalidRequestError
        ``validation_error`` (400) with the standard's ``reason`` and the formula,
        the constraint or the input it names; ``invalid_parameters`` with Hydrolog's
        message for a reason outside the standard's three.
    """
    details: Mapping[str, Any] = (
        error.details if isinstance(error.details, Mapping) else {}
    )
    reason = details.get("reason")
    formula = str(details.get("formula") or "")
    constraint = details.get("constraint")
    if reason in ("outside_physical_range", "precondition_failed") and isinstance(
        constraint, str
    ):
        return _constraint(str(reason), formula, constraint, details)
    option = str(details.get("option") or details.get("variable") or "")
    if reason == "outside_physical_range":
        return InvalidRequestError(
            "formula_input_outside_physical_range",
            reason="outside_physical_range",
            formula=formula,
            option=option,
            value=_number(details.get("value")),
            range=_range(details.get("range")),
        )
    if reason == "invalid_type":
        return InvalidRequestError(
            "formula_input_invalid_type",
            reason="invalid_type",
            formula=formula,
            option=option,
        )
    return InvalidRequestError(
        "invalid_parameters", reason="invalid_parameters", cause=str(error)
    )


def _constraint(
    reason: str, formula: str, constraint: str, details: Mapping[str, Any]
) -> InvalidRequestError:
    """Return the error of a broken physical condition or failed precondition."""
    if constraint == "centroid_within_length":
        return InvalidRequestError(
            "lutz_centroid_beyond_length",
            reason=reason,
            formula=formula,
            constraint=constraint,
        )
    if constraint == "shares_within_catchment":
        return InvalidRequestError(
            "lutz_shares_over_area",
            reason=reason,
            formula=formula,
            constraint=constraint,
        )
    if constraint == "flow_path_longer_than_overland":
        return InvalidRequestError(
            "kerby_kirpich_overland_not_shorter",
            reason=reason,
            formula=formula,
            constraint=constraint,
        )
    text = str(details.get("text") or constraint)
    if reason == "outside_physical_range":
        return InvalidRequestError(
            "formula_physical_condition",
            reason=reason,
            formula=formula,
            constraint=constraint,
            text=text,
        )
    return InvalidRequestError(
        "formula_precondition_failed",
        reason=reason,
        formula=formula,
        constraint=constraint,
        text=text,
    )


def _number(value: object) -> str:
    """Write a refused value as text: a number in full, anything else as given."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:g}" if math.isfinite(value) else str(value)


def _range(bounds: object) -> str:
    """Write Hydrolog's ``details.range`` as ``(0, ∞)`` or ``[0, 1]``."""
    if not isinstance(bounds, Mapping):
        return "–"
    low, high = bounds.get("low"), bounds.get("high")
    left = "[" if bounds.get("low_inclusive") else "("
    right = "]" if bounds.get("high_inclusive") else ")"
    low_text = _number(low) if isinstance(low, int | float) else "−∞"
    high_text = _number(high) if isinstance(high, int | float) else "∞"
    return f"{left}{low_text}, {high_text}{right}"
