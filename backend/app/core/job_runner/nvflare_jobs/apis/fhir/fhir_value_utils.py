from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except Exception:
        return None


def get_fhir_numeric_value(
    resource: Dict[str, Any],
    primitive_keys: Sequence[str] = ("valueInteger",),
) -> Optional[float]:
    """Return a numeric FHIR value[x], preferring valueQuantity.value.

    Existing datasets store numeric data as valueQuantity.value. Newer datasets may
    store the same numeric value as a primitive valueInteger. This helper keeps
    valueQuantity as the primary source and only falls back to primitive value[x]
    keys when the quantity value is absent or cannot be parsed.
    """
    if not isinstance(resource, dict):
        return None

    value_quantity = resource.get("valueQuantity") or {}
    if isinstance(value_quantity, dict):
        quantity_value = _coerce_float(value_quantity.get("value"))
        if quantity_value is not None:
            return quantity_value

    for key in primitive_keys:
        primitive_value = _coerce_float(resource.get(key))
        if primitive_value is not None:
            return primitive_value

    return None
