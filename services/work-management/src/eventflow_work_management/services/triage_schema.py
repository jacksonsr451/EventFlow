"""Safe, declarative validation for project triage configuration (Issue #41).

Administrators never submit executable validation code. A template definition is
a bounded JSON document made of flat field descriptors, required-field names,
defaults, presentation hints and a small closed set of workflow switches. This
module is the single authoritative validator for both template definitions and
submitted custom-field values. It has no database access and no hidden state, so
the same validation runs during configuration writes, triage, previews and
tests.

Explicit limits protect against recursive, deeply nested, oversized or
regex-based denial of service:

* at most 100 custom fields per definition;
* at most 100 enum choices per field;
* at most 64 KiB of canonical JSON per definition;
* no regular expressions, SQL, expressions, imports, remote references, or
  executable constructs are accepted at all;
* values are length and range bounded.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any

from eventflow_work_management.models.enums import (
    TRIAGE_CATEGORY_VALUES,
    TRIAGE_FIELD_STATUS_VALUES,
    TRIAGE_FIELD_TYPE_VALUES,
)
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.triage_criteria import CRITERIA_MODELS

MAX_FIELDS = 100
MAX_ENUM_VALUES = 100
MAX_DEFINITION_BYTES = 64 * 1024
MAX_NODES = 2000
MAX_DEPTH = 6
MAX_STRING_LENGTH = 10_000
MAX_DESCRIPTION_LENGTH = 500
MAX_LABEL_LENGTH = 120

FIELD_KEYS = frozenset(
    {
        "key",
        "label",
        "description",
        "type",
        "required",
        "default",
        "allowed_values",
        "minimum",
        "maximum",
        "min_length",
        "max_length",
        "categories",
        "order",
        "status",
    }
)

DEFINITION_KEYS = frozenset(
    {"fields", "required_fields", "defaults", "workflow", "presentation"}
)

WORKFLOW_KEYS = frozenset(
    {
        "require_template_for_new_triage",
        "require_priority_inputs",
        "triage_notes_min_length",
        "require_justification_for_reclassification",
        "allowed_triage_categories",
        "allowed_reclassification_targets",
        "require_evidence_for_categories",
    }
)

# Keys that would indicate executable code, remote schema references or
# unbounded pattern matching. They are rejected anywhere in a definition.
UNSAFE_KEYS = frozenset(
    {
        "$ref",
        "$schema",
        "script",
        "scripts",
        "expression",
        "expressions",
        "sql",
        "eval",
        "exec",
        "execute",
        "import",
        "imports",
        "require",
        "command",
        "shell",
        "url",
        "uri",
        "href",
        "remote",
        "regex",
        "regexp",
        "pattern",
        "x-",
    }
)

BYPASS_MARKERS = (
    "approve",
    "approval",
    "work_item",
    "workitem",
    "board",
    "bypass",
    "auto",
    "skip",
)

SYSTEM_FIELD_KEYS = frozenset(
    {
        "id",
        "workspace_id",
        "project_id",
        "consultation_id",
        "category",
        "priority",
        "triage_notes",
        "custom_fields",
        "status",
        "title",
        "description",
        "origin",
        "created_at",
        "updated_at",
        "template_id",
        "template_version",
    }
)

CORE_CRITERIA_KEYS: frozenset[str] = frozenset(
    key for model in CRITERIA_MODELS.values() for key in model.model_fields
)

RESERVED_FIELD_KEYS = SYSTEM_FIELD_KEYS | CORE_CRITERIA_KEYS

_STRING_TYPES = frozenset({"string", "multiline_text", "reference"})
_NUMERIC_TYPES = frozenset({"integer", "number"})
_CHOICE_TYPES = frozenset({"enum", "multi_select"})

# ASCII-only identifier alphabet so a key can never smuggle non-ASCII lookalikes
# into an audit record or column.
_LOWERCASE = "abcdefghijklmnopqrstuvwxyz"
_DIGITS = "0123456789"


def _problem(
    detail: str,
    *,
    errors: list[dict] | None = None,
    code: str = "TRIAGE_FIELD_INVALID",
    status_code: int = 422,
) -> ProblemError:
    return ProblemError(
        status_code=status_code,
        code=code,
        detail=detail,
        title="Unprocessable entity" if status_code == 422 else "Invalid request",
        errors=errors,
    )


def _field_error(key: str, message: str) -> dict:
    return {"field": key, "message": message}


def _reject_unsafe(node: Any, *, path: str = "definition", depth: int = 0) -> int:
    """Reject executable/remote constructs and bound the document shape."""
    if depth > MAX_DEPTH:
        raise _problem("The template definition is nested too deeply.")
    nodes = 1
    if isinstance(node, dict):
        if len(node) > MAX_FIELDS:
            raise _problem("The template definition contains too many properties.")
        for key, value in node.items():
            if not isinstance(key, str):
                raise _problem("The template definition contains a non-string key.")
            lowered = key.lower()
            if lowered in UNSAFE_KEYS or any(
                lowered.startswith(marker) for marker in ("x-", "$")
            ):
                raise _problem(
                    "The template definition contains an unsupported or unsafe "
                    "validation keyword."
                )
            nodes += _reject_unsafe(value, path=f"{path}.{key}", depth=depth + 1)
            if nodes > MAX_NODES:
                raise _problem("The template definition is too large.")
    elif isinstance(node, list):
        if len(node) > MAX_FIELDS:
            raise _problem("The template definition contains too many items.")
        for index, item in enumerate(node):
            nodes += _reject_unsafe(
                item, path=f"{path}[{index}]", depth=depth + 1
            )
            if nodes > MAX_NODES:
                raise _problem("The template definition is too large.")
    elif isinstance(node, str):
        if len(node) > MAX_STRING_LENGTH:
            raise _problem("A template definition string is too long.")
    elif isinstance(node, (int, float, bool)) or node is None:
        return nodes
    else:
        raise _problem("The template definition contains an unsupported value.")
    return nodes


def _require_categories(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _problem(
            "A field must declare at least one applicable category.",
            errors=[_field_error(field, "categories must be a non-empty array")],
        )
    if len(value) > len(TRIAGE_CATEGORY_VALUES):
        raise _problem("Too many categories on a field.")
    result: list[str] = []
    for category in value:
        if not isinstance(category, str) or category not in TRIAGE_CATEGORY_VALUES:
            raise _problem(
                "A field declares an unknown triage category.",
                errors=[_field_error(field, "unknown category")],
            )
        if category not in result:
            result.append(category)
    return result


def _validate_scalar_default(field: dict, value: Any) -> None:
    key = field["key"]
    field_type = field["type"]
    if value is None:
        return
    if field_type in _STRING_TYPES:
        if not isinstance(value, str):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected a string default")],
            )
        if field_type == "reference" and not value.strip():
            raise _problem(
                "A reference default cannot be empty.",
                errors=[_field_error(key, "empty reference default")],
            )
        if len(value) > MAX_STRING_LENGTH:
            raise _problem(
                "A default value is too long.",
                errors=[_field_error(key, "string default is too long")],
            )
    elif field_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected an integer default")],
            )
    elif field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected a numeric default")],
            )
    elif field_type == "boolean":
        if not isinstance(value, bool):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected a boolean default")],
            )
    elif field_type == "date":
        if not isinstance(value, str):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected a date string default")],
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected an ISO date default")],
            ) from exc
    elif field_type == "datetime":
        if not isinstance(value, str):
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected a datetime string default")],
            )
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise _problem(
                "A default value does not match the field type.",
                errors=[_field_error(key, "expected an ISO datetime default")],
            ) from exc
    elif field_type == "enum":
        if not isinstance(value, str) or value not in field["allowed_values"]:
            raise _problem(
                "A default value is not an allowed choice.",
                errors=[_field_error(key, "default is not in allowed_values")],
            )
    elif field_type == "multi_select":
        if not isinstance(value, list) or any(
            not isinstance(item, str) or item not in field["allowed_values"]
            for item in value
        ):
            raise _problem(
                "A default value is not an allowed choice.",
                errors=[_field_error(key, "default is not in allowed_values")],
            )
        if len(value) != len(set(value)):
            raise _problem(
                "A multi-select default contains duplicate choices.",
                errors=[_field_error(key, "duplicate default choice")],
            )


def _validate_number(value: Any, key: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _problem(
            "A numeric boundary is invalid.",
            errors=[_field_error(key, "boundary must be numeric")],
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise _problem(
            "A numeric boundary is invalid.",
            errors=[_field_error(key, "boundary must be finite")],
        )
    return value


def _normalize_field(raw: Any, *, template_category: str | None) -> dict:
    if not isinstance(raw, dict):
        raise _problem("Each custom field must be an object.")
    unknown = set(raw) - FIELD_KEYS
    if unknown:
        raise _problem(
            "A custom field contains an unsupported property.",
            errors=[_field_error(str(sorted(unknown)[0]), "unsupported property")],
        )
    key = raw.get("key")
    if (
        not isinstance(key, str)
        or not 2 <= len(key) <= 64
        or key[0] not in _LOWERCASE
        or any(char not in _LOWERCASE + _DIGITS + "_" for char in key)
    ):
        raise _problem(
            "A custom field key is invalid.",
            errors=[_field_error(str(key), "key must match ^[a-z][a-z0-9_]{1,63}$")],
        )
    if key in RESERVED_FIELD_KEYS:
        raise _problem(
            "A custom field uses a reserved key.",
            errors=[_field_error(key, "reserved field key")],
        )
    label = raw.get("label")
    if not isinstance(label, str) or not 1 <= len(label) <= MAX_LABEL_LENGTH:
        raise _problem(
            "A custom field label is invalid.",
            errors=[_field_error(key, "label must be 1 to 120 characters")],
        )
    description = raw.get("description")
    if description is not None and (
        not isinstance(description, str)
        or len(description) > MAX_DESCRIPTION_LENGTH
    ):
        raise _problem(
            "A custom field description is invalid.",
            errors=[_field_error(key, "description must be at most 500 characters")],
        )
    field_type = raw.get("type")
    if field_type not in TRIAGE_FIELD_TYPE_VALUES:
        raise _problem(
            "A custom field type is unsupported.",
            errors=[_field_error(key, "unsupported field type")],
        )
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise _problem(
            "A custom field required flag is invalid.",
            errors=[_field_error(key, "required must be a boolean")],
        )
    categories = raw.get("categories")
    if categories is None:
        categories = [template_category] if template_category else list(
            TRIAGE_CATEGORY_VALUES
        )
    categories = _require_categories(categories, key)
    if template_category is not None and template_category not in categories:
        raise _problem(
            "A template field is not applicable to the template category.",
            errors=[_field_error(key, "categories must include the template category")],
        )
    status = raw.get("status", "active")
    if status not in TRIAGE_FIELD_STATUS_VALUES:
        raise _problem(
            "A custom field lifecycle status is invalid.",
            errors=[_field_error(key, "unsupported field status")],
        )
    order = raw.get("order", 0)
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10000:
        raise _problem(
            "A custom field order is invalid.",
            errors=[_field_error(key, "order must be 0 to 10000")],
        )

    allowed_values = raw.get("allowed_values")
    minimum = raw.get("minimum")
    maximum = raw.get("maximum")
    min_length = raw.get("min_length")
    max_length = raw.get("max_length")

    normalized: dict = {
        "key": key,
        "label": label,
        "description": description,
        "type": field_type,
        "required": required,
        "allowed_values": None,
        "minimum": None,
        "maximum": None,
        "min_length": None,
        "max_length": None,
        "categories": categories,
        "order": order,
        "status": status,
    }

    if field_type in _CHOICE_TYPES:
        if not isinstance(allowed_values, list) or not allowed_values:
            raise _problem(
                "An enum field must declare allowed values.",
                errors=[_field_error(key, "allowed_values is required")],
            )
        if len(allowed_values) > MAX_ENUM_VALUES:
            raise _problem(
                "An enum field declares too many choices.",
                errors=[_field_error(key, "at most 100 allowed values")],
            )
        choices: list[str] = []
        for choice in allowed_values:
            if not isinstance(choice, str) or not 1 <= len(choice) <= 100:
                raise _problem(
                    "An allowed value is invalid.",
                    errors=[_field_error(key, "choices must be 1 to 100 characters")],
                )
            if choice in choices:
                raise _problem(
                    "An allowed value is duplicated.",
                    errors=[_field_error(key, "duplicate allowed value")],
                )
            choices.append(choice)
        normalized["allowed_values"] = choices
        if minimum is not None or maximum is not None:
            raise _problem(
                "An enum field cannot declare numeric boundaries.",
                errors=[_field_error(key, "numeric boundaries are not applicable")],
            )
    elif allowed_values is not None:
        raise _problem(
            "Only enum and multi-select fields may declare allowed values.",
            errors=[_field_error(key, "allowed_values is not applicable")],
        )

    if field_type in _NUMERIC_TYPES:
        if minimum is not None:
            normalized["minimum"] = _validate_number(minimum, key)
        if maximum is not None:
            normalized["maximum"] = _validate_number(maximum, key)
        if (
            normalized["minimum"] is not None
            and normalized["maximum"] is not None
            and normalized["minimum"] > normalized["maximum"]
        ):
            raise _problem(
                "A numeric range is inverted.",
                errors=[_field_error(key, "minimum must not exceed maximum")],
            )
        if min_length is not None or max_length is not None:
            raise _problem(
                "A numeric field cannot declare string length limits.",
                errors=[_field_error(key, "length limits are not applicable")],
            )
    elif field_type in _STRING_TYPES:
        if minimum is not None or maximum is not None:
            raise _problem(
                "A text field cannot declare numeric boundaries.",
                errors=[_field_error(key, "numeric boundaries are not applicable")],
            )
        for name, value in (("min_length", min_length), ("max_length", max_length)):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= MAX_STRING_LENGTH
            ):
                raise _problem(
                    "A text length limit is invalid.",
                    errors=[_field_error(key, f"{name} must be 0 to 10000")],
                )
            normalized[name] = value
        if (
            normalized["min_length"] is not None
            and normalized["max_length"] is not None
            and normalized["min_length"] > normalized["max_length"]
        ):
            raise _problem(
                "A text length range is inverted.",
                errors=[_field_error(key, "min_length must not exceed max_length")],
            )
    elif minimum is not None or maximum is not None:
        raise _problem(
            "This field type cannot declare numeric boundaries.",
            errors=[_field_error(key, "numeric boundaries are not applicable")],
        )

    if min_length is not None or max_length is not None:
        if field_type not in _STRING_TYPES:
            raise _problem(
                "Only text fields may declare length limits.",
                errors=[_field_error(key, "length limits are not applicable")],
            )

    if "default" in raw:
        default = raw["default"]
        _validate_scalar_default(normalized, default)
        normalized["default"] = default
    else:
        normalized["default"] = None
    return normalized


def validate_field_definitions(
    fields: Any, *, template_category: str | None = None
) -> list[dict]:
    """Validate and normalize a flat list of custom field definitions."""
    if fields is None:
        return []
    if not isinstance(fields, list):
        raise _problem("Custom fields must be an array.")
    if len(fields) > MAX_FIELDS:
        raise _problem("A definition may declare at most 100 custom fields.")
    normalized: list[dict] = []
    seen: set[str] = set()
    for raw in fields:
        field = _normalize_field(raw, template_category=template_category)
        if field["key"] in seen:
            raise _problem(
                "A custom field key is duplicated.",
                errors=[_field_error(field["key"], "duplicate field key")],
            )
        seen.add(field["key"])
        normalized.append(field)
    return normalized


def validate_required_fields(raw: Any) -> dict[str, list[str]]:
    """Validate the configuration's per-category additional required fields."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _problem("required_fields must be an object keyed by category.")
    result: dict[str, list[str]] = {}
    for category, keys in raw.items():
        if category not in TRIAGE_CATEGORY_VALUES:
            raise _problem(
                "required_fields declares an unknown category.",
                errors=[_field_error(str(category), "unknown category")],
            )
        if not isinstance(keys, list) or len(keys) > MAX_FIELDS:
            raise _problem(
                "required_fields must be an array with at most 100 keys.",
                errors=[_field_error(category, "invalid required field list")],
            )
        unique: list[str] = []
        for key in keys:
            if not isinstance(key, str) or not key:
                raise _problem(
                    "A required field key is invalid.",
                    errors=[_field_error(category, "required keys must be strings")],
                )
            if key in RESERVED_FIELD_KEYS and key not in CORE_CRITERIA_KEYS:
                raise _problem(
                    "A required field references a system key.",
                    errors=[_field_error(key, "reserved field key")],
                )
            if key not in unique:
                unique.append(key)
        result[category] = unique
    return result


def validate_workflow_rules(raw: Any) -> dict:
    """Validate the closed workflow-rule vocabulary; reject bypass attempts."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _problem("workflow_rules must be an object.")
    result: dict = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise _problem("A workflow rule key must be a string.")
        lowered = key.lower()
        if key not in WORKFLOW_KEYS:
            if any(marker in lowered for marker in BYPASS_MARKERS):
                raise _problem(
                    "Project workflow rules cannot bypass approval or domain "
                    "invariants.",
                    code="TRIAGE_WORKFLOW_VIOLATION",
                )
            raise _problem(
                "A workflow rule is not supported.",
                errors=[_field_error(key, "unsupported workflow rule")],
            )
        if key == "require_template_for_new_triage":
            if not isinstance(value, bool):
                raise _problem("require_template_for_new_triage must be a boolean.")
            result[key] = value
        elif key == "require_priority_inputs":
            if not isinstance(value, bool):
                raise _problem("require_priority_inputs must be a boolean.")
            result[key] = value
        elif key == "require_justification_for_reclassification":
            if value is not True:
                raise _problem(
                    "Reclassification always requires a justification.",
                    code="TRIAGE_WORKFLOW_VIOLATION",
                )
            result[key] = True
        elif key == "triage_notes_min_length":
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 5 <= value <= 5000
            ):
                raise _problem("triage_notes_min_length must be 5 to 5000.")
            result[key] = value
        elif key in {
            "allowed_triage_categories",
            "allowed_reclassification_targets",
            "require_evidence_for_categories",
        }:
            if not isinstance(value, list) or len(value) > len(TRIAGE_CATEGORY_VALUES):
                raise _problem(f"{key} must be a category array.")
            unique: list[str] = []
            for category in value:
                if category not in TRIAGE_CATEGORY_VALUES:
                    raise _problem(f"{key} contains an unknown category.")
                if category not in unique:
                    unique.append(category)
            result[key] = unique
    return result


def validate_presentation(raw: Any) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or len(raw) > 50:
        raise _problem("presentation must be a small object.")
    for key, value in raw.items():
        if not isinstance(key, str) or len(key) > 64:
            raise _problem("A presentation key is invalid.")
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
                raise _problem("A presentation value is too long.")
            continue
        if isinstance(value, list) and len(value) <= 100 and all(
            isinstance(item, (str, int, float, bool)) or item is None
            for item in value
        ):
            continue
        raise _problem("Presentation hints must be declarative scalar values.")
    return dict(raw)


def validate_template_definition(definition: Any, *, category: str) -> dict:
    """Validate one template definition and return its canonical normalized form."""
    if category not in TRIAGE_CATEGORY_VALUES:
        raise _problem("Unknown triage category.", code="TRIAGE_TEMPLATE_MISMATCH")
    if not isinstance(definition, dict):
        raise _problem("A template definition must be an object.")
    try:
        encoded = json.dumps(
            definition, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _problem("The template definition is not valid JSON.") from exc
    if len(encoded) > MAX_DEFINITION_BYTES:
        raise _problem("The template definition exceeds the 64 KiB limit.")
    _reject_unsafe(definition)
    unknown = set(definition) - DEFINITION_KEYS
    if unknown:
        raise _problem(
            "The template definition contains an unsupported property.",
            errors=[_field_error(str(sorted(unknown)[0]), "unsupported property")],
        )
    fields = validate_field_definitions(
        definition.get("fields"), template_category=category
    )
    field_keys = {field["key"] for field in fields}
    required_fields = definition.get("required_fields", [])
    if not isinstance(required_fields, list) or len(required_fields) > MAX_FIELDS:
        raise _problem("required_fields must be an array with at most 100 keys.")
    normalized_required: list[str] = []
    for key in required_fields:
        if not isinstance(key, str) or key not in field_keys:
            raise _problem(
                "A required field does not exist in the template.",
                errors=[_field_error(str(key), "unknown required field")],
            )
        if key not in normalized_required:
            normalized_required.append(key)
    defaults = definition.get("defaults", {})
    if not isinstance(defaults, dict) or len(defaults) > MAX_FIELDS:
        raise _problem("defaults must be an object with at most 100 entries.")
    by_key = {field["key"]: field for field in fields}
    normalized_defaults: dict = {}
    for key, value in defaults.items():
        if not isinstance(key, str) or key not in by_key:
            raise _problem(
                "A default references an unknown field.",
                errors=[_field_error(str(key), "unknown default field")],
            )
        _validate_scalar_default(by_key[key], value)
        normalized_defaults[key] = value
    workflow = validate_workflow_rules(definition.get("workflow"))
    presentation = validate_presentation(definition.get("presentation"))
    return {
        "fields": fields,
        "required_fields": normalized_required,
        "defaults": normalized_defaults,
        "workflow": workflow,
        "presentation": presentation,
    }


def merge_workflow_rules(
    configuration_rules: dict | None, template_rules: dict | None
) -> dict:
    """Combine project and template rules without ever weakening a restriction."""
    merged: dict = dict(configuration_rules or {})
    template_rules = template_rules or {}
    for key, value in template_rules.items():
        if key in {"require_template_for_new_triage", "require_priority_inputs"}:
            merged[key] = bool(merged.get(key)) or bool(value)
        elif key == "triage_notes_min_length":
            merged[key] = max(int(merged.get(key, 5)), int(value))
        elif key == "require_justification_for_reclassification":
            merged[key] = True
        elif key == "allowed_triage_categories":
            current = merged.get(key)
            merged[key] = (
                [item for item in current if item in value] if current else list(value)
            )
        elif key == "allowed_reclassification_targets":
            current = merged.get(key)
            merged[key] = (
                [item for item in current if item in value] if current else list(value)
            )
        elif key == "require_evidence_for_categories":
            current = list(merged.get(key, []))
            merged[key] = current + [item for item in value if item not in current]
    return merged


def _value_problem(errors: list[dict], key: str, message: str) -> None:
    errors.append(_field_error(key, message))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def apply_and_validate_field_values(
    fields: list[dict],
    values: Any,
    *,
    required_keys: set[str] | frozenset[str] = frozenset(),
) -> dict:
    """Apply defaults and validate submitted custom-field values.

    Raises one structured ``422`` problem listing every field-level failure.
    Unknown keys are rejected so a client cannot smuggle data past the schema.
    """
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise _problem(
            "custom_fields must be an object.",
            errors=[_field_error("custom_fields", "expected an object")],
        )
    by_key = {field["key"]: field for field in fields}
    errors: list[dict] = []
    for key in values:
        if key not in by_key:
            _value_problem(errors, str(key), "unexpected custom field")
    normalized: dict = {}
    for field in fields:
        key = field["key"]
        if field["status"] != "active":
            continue
        required = bool(field["required"]) or key in required_keys
        value = values.get(key)
        if _is_empty(value):
            if field["default"] is not None:
                normalized[key] = field["default"]
                continue
            if required:
                _value_problem(errors, key, "This field is required.")
            else:
                normalized[key] = None
            continue
        field_type = field["type"]
        if field_type in _STRING_TYPES:
            if not isinstance(value, str):
                _value_problem(errors, key, "Expected a string.")
                continue
            if field_type == "reference" and not value.strip():
                _value_problem(errors, key, "A reference cannot be empty.")
                continue
            if field["min_length"] is not None and len(value) < field["min_length"]:
                _value_problem(errors, key, "The value is shorter than permitted.")
            if len(value) > MAX_STRING_LENGTH:
                _value_problem(errors, key, "The value is longer than permitted.")
            elif field["max_length"] is not None and len(value) > field["max_length"]:
                _value_problem(errors, key, "The value is longer than permitted.")
        elif field_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                _value_problem(errors, key, "Expected an integer.")
                continue
            if field["minimum"] is not None and value < field["minimum"]:
                _value_problem(errors, key, "The value is below the minimum.")
            if field["maximum"] is not None and value > field["maximum"]:
                _value_problem(errors, key, "The value is above the maximum.")
        elif field_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _value_problem(errors, key, "Expected a number.")
                continue
            if isinstance(value, float) and not math.isfinite(value):
                _value_problem(errors, key, "Expected a finite number.")
                continue
            if field["minimum"] is not None and value < field["minimum"]:
                _value_problem(errors, key, "The value is below the minimum.")
            if field["maximum"] is not None and value > field["maximum"]:
                _value_problem(errors, key, "The value is above the maximum.")
        elif field_type == "boolean":
            if not isinstance(value, bool):
                _value_problem(errors, key, "Expected a boolean.")
                continue
        elif field_type == "date":
            if not isinstance(value, str):
                _value_problem(errors, key, "Expected an ISO date string.")
                continue
            try:
                date.fromisoformat(value)
            except ValueError:
                _value_problem(errors, key, "Expected an ISO date string.")
                continue
        elif field_type == "datetime":
            if not isinstance(value, str):
                _value_problem(errors, key, "Expected an ISO datetime string.")
                continue
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _value_problem(errors, key, "Expected an ISO datetime string.")
                continue
        elif field_type == "enum":
            if not isinstance(value, str) or value not in field["allowed_values"]:
                _value_problem(errors, key, "Expected one of the allowed values.")
                continue
        elif field_type == "multi_select":
            if not isinstance(value, list):
                _value_problem(errors, key, "Expected an array of allowed values.")
                continue
            if len(value) > MAX_ENUM_VALUES:
                _value_problem(errors, key, "Too many selected values.")
                continue
            if len(value) != len(set(value)):
                _value_problem(errors, key, "Duplicate selected values.")
                continue
            if any(
                not isinstance(item, str) or item not in field["allowed_values"]
                for item in value
            ):
                _value_problem(errors, key, "Expected only allowed values.")
                continue
        normalized[key] = value

    missing = [
        error for error in errors if error["message"] == "This field is required."
    ]
    if missing:
        raise _problem(
            "Required triage fields are missing.",
            code="TRIAGE_REQUIRED_FIELD_MISSING",
            errors=errors,
        )
    if errors:
        raise _problem(
            "One or more custom triage fields are invalid.",
            errors=errors,
        )
    return normalized


def evaluate_workflow(
    rules: dict,
    *,
    category: str,
    action: str,
    current_category: str | None = None,
    triage_notes: str | None = None,
    business_impact: str | None = None,
    business_urgency: str | None = None,
    has_evidence: bool = False,
) -> None:
    """Raise a stable workflow problem when the project rules deny the action."""
    if action == "triage":
        allowed = rules.get("allowed_triage_categories")
        if allowed and category not in allowed:
            raise _problem(
                "The project does not permit triage into this category.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
        if rules.get("require_priority_inputs") and (
            business_impact is None or business_urgency is None
        ):
            raise _problem(
                "The project requires business impact and urgency for triage.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
        minimum = rules.get("triage_notes_min_length")
        if minimum is not None and (
            triage_notes is None or len(triage_notes) < int(minimum)
        ):
            raise _problem(
                "The project requires longer triage notes.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
    elif action == "reclassify":
        targets = rules.get("allowed_reclassification_targets")
        if targets and category not in targets:
            raise _problem(
                "The project does not permit reclassification into this category.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
        if (
            rules.get("require_justification_for_reclassification", True)
            and current_category is None
        ):
            raise _problem(
                "The consultation has no previous category.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
    elif action == "proposal":
        required_evidence = rules.get("require_evidence_for_categories") or []
        if category in required_evidence and not has_evidence:
            raise _problem(
                "The project requires evidence before a proposal can be created.",
                code="TRIAGE_WORKFLOW_VIOLATION",
            )
