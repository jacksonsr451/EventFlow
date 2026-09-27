#!/usr/bin/env python3
"""Validate the repository's current contract and documentation baseline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas"
EVENTS = SCHEMAS / "events.yaml"
EXAMPLE = CONTRACTS / "examples" / "order-workflow.json"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TEXT_SUFFIXES = {".json", ".md", ".py", ".yaml", ".yml"}


def load_document(path: Path):
    with path.open(encoding="utf-8") as stream:
        if path.suffix == ".json":
            return json.load(stream)
        return yaml.safe_load(stream)


def json_pointer(document, fragment: str):
    value = document
    for raw_segment in fragment.lstrip("/").split("/"):
        if not raw_segment:
            continue
        segment = unquote(raw_segment).replace("~1", "/").replace("~0", "~")
        value = value[int(segment)] if isinstance(value, list) else value[segment]
    return value


def validate_local_refs(paths: list[Path]) -> None:
    documents = {path.resolve(): load_document(path) for path in paths}
    for source, document in documents.items():
        refs = []

        def collect(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    refs.append(value["$ref"])
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(document)
        for reference in refs:
            if reference.startswith("#"):
                target = source
                fragment = reference[1:]
            else:
                target_name, _, fragment = reference.partition("#")
                target = (source.parent / urlparse(target_name).path).resolve()
            if target not in documents:
                if not target.exists():
                    raise AssertionError(f"broken local ref: {source}: {reference}")
                documents[target] = load_document(target)
            if fragment:
                json_pointer(documents[target], fragment)


def event_schema_names(event_document: dict) -> dict[str, str]:
    result = {}
    for name, schema in event_document["$defs"].items():
        if not isinstance(schema, dict):
            continue
        for branch in schema.get("allOf", []):
            event_type = branch.get("properties", {}).get("event_type", {}).get("const")
            if event_type:
                result[event_type] = name
    return result


def validate_schemas_and_example() -> None:
    schema_documents = {path.name: load_document(path) for path in SCHEMAS.glob("*.yaml")}
    for document in schema_documents.values():
        Draft202012Validator.check_schema(document)

    registry = Registry()
    for name, document in schema_documents.items():
        registry = registry.with_resource(
            (SCHEMAS / name).resolve().as_uri(), Resource.from_contents(document)
        )

    event_document = schema_documents[EVENTS.name]
    event_names = event_schema_names(event_document)
    asyncapi = load_document(CONTRACTS / "asyncapi" / "workflow.yaml")
    messages = asyncapi["components"]["messages"]
    message_event_types = set()
    for message in messages.values():
        event_type = message["name"]
        reference = message["payload"]["$ref"]
        expected_name = event_names.get(event_type)
        message_event_types.add(event_type)
        expected_reference = f"../schemas/events.yaml#/$defs/{expected_name}"
        if not expected_name or reference != expected_reference:
            raise AssertionError(f"AsyncAPI message is not mapped to its event schema: {event_type}")
    if len(message_event_types) != len(messages):
        raise AssertionError("AsyncAPI messages contain duplicate event types")
    if message_event_types != set(event_names):
        raise AssertionError("AsyncAPI messages and event schemas are out of sync")

    events = load_document(EXAMPLE)
    format_checker = FormatChecker()
    for event in events:
        schema_name = event_names.get(event["event_type"])
        if not schema_name:
            raise AssertionError(f"example uses an unknown event type: {event['event_type']}")
        Draft202012Validator(
            {"$ref": f"{EVENTS.resolve().as_uri()}#/$defs/{schema_name}"},
            registry=registry,
            format_checker=format_checker,
        ).validate(event)

    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise AssertionError("workflow example contains duplicate event_id values")
    if len({event["correlation_id"] for event in events}) != 1:
        raise AssertionError("workflow example does not keep correlation_id stable")
    if len({event["payload"]["order_id"] for event in events}) != 1:
        raise AssertionError("workflow example does not keep order_id stable")
    for index, event in enumerate(events):
        expected_causation = None if index == 0 else events[index - 1]["event_id"]
        if event["causation_id"] != expected_causation:
            raise AssertionError("workflow example has an incoherent causation_id chain")

    stable_ids = {"reservation_id": set(), "payment_id": set(), "compensation_id": set()}
    for event in events:
        for name, values in stable_ids.items():
            if name in event["payload"]:
                values.add(event["payload"][name])
    for name, values in stable_ids.items():
        if len(values) > 1:
            raise AssertionError(f"workflow example changes {name} during one operation")


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if (ROOT / line).is_file()]


def validate_markdown_links(paths: list[Path]) -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for source in paths:
        if source.suffix != ".md":
            continue
        for target in link_pattern.findall(source.read_text(encoding="utf-8")):
            target = target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (source.parent / target).exists():
                raise AssertionError(f"broken Markdown link: {source}: {target}")


def validate_text_whitespace(paths: list[Path]) -> None:
    for path in paths:
        if path.suffix not in TEXT_SUFFIXES and path.name not in {".gitattributes", "Makefile"}:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.endswith((" ", "\t")):
                raise AssertionError(f"trailing whitespace: {path}:{line_number}")


def main() -> int:
    contract_files = list(CONTRACTS.rglob("*.yaml")) + list(CONTRACTS.rglob("*.json"))
    for path in contract_files:
        load_document(path)
    load_document(WORKFLOW)
    validate_local_refs(contract_files)
    validate_schemas_and_example()
    files = repository_files()
    validate_markdown_links(files)
    validate_text_whitespace(files)
    print("Contract, reference, example, Markdown-link, and whitespace validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
