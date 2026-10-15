# Order Processing Regression Strategy

Order Processing has no running service on `main`, so its regressions are
**contract regressions**. This strategy freezes the observable contract surface
and makes every intentional change an explicit, reviewed diff.

## What Is Protected

- The set of Order Processing contract files and the event taxonomy.
- Every `required` field path and every `enum` value in the shared schemas, per
  file: `common.yaml`, `http.yaml`, `events.yaml`, `envelope.yaml`.
- The HTTP surface of `orders.yaml`: paths and operations.
- The AsyncAPI surface of `workflow.yaml`: channels, operations, messages.
- The shared envelope requirement: every event references the envelope and pins
  `schema_version` to `1`.
- The error media type and shape: `application/problem+json` with
  `http.yaml#/$defs/ErrorResponse`.
- The boundary between Order Processing and Work Management.
- The presence and cross-linking of this documentation set.

## The Compatibility Baseline

[`tests/contracts/order_processing_baseline.json`](../../../tests/contracts/order_processing_baseline.json)
is a frozen snapshot keyed by contract file. For each schema file it stores the
sorted `required` and `enum` paths; it also stores the `EventType` enum, the
error `code` enum, the `orders.yaml` operations and the AsyncAPI
channels/operations/messages.

The test
[`tests/contracts/test_order_processing_preservation.py`](../../../tests/contracts/test_order_processing_preservation.py)
recomputes the snapshot and fails on any difference. A failure means the
contract surface changed — which may be legitimate, but it may never pass
silently.

## Review Process for an Intentional Change

1. Change the contract (`contracts/`).
2. Run the preservation tests and read the diff.
3. Confirm the change is either additive-optional (compatible) or is an
   intentional breaking change.
4. If breaking, add an ADR and a versioning/migration note per
   [compatibility.md](compatibility.md).
5. Regenerate the baseline with the same script that produced it and commit the
   baseline next to the contract change, with the reason in the commit message.
6. Re-run `validate_contracts.py`, the test suite and pre-commit.

Baseline regeneration is deliberately manual: the snapshot must be updated by a
reviewer who understands why it changed, never automatically in CI.

## Test Inventory

| Test | Protects |
|---|---|
| `test_order_processing_contract_files_exist` | Contract files are present |
| `test_contracts_match_the_compatibility_baseline` | Required paths, enums, HTTP/AsyncAPI surface |
| `test_event_taxonomy_is_consistent` | Schemas ↔ `EventType` ↔ AsyncAPI messages |
| `test_every_event_uses_the_common_envelope` | Envelope reuse and `schema_version` pin |
| `test_asyncapi_messages_map_to_their_event_schema` | Message → schema reference mapping |
| `test_order_operations_require_bearer_auth` | Authentication on Orders operations |
| `test_order_error_responses_use_problem_json` | Error media type and shared shape |
| `test_order_contracts_do_not_reference_work_management` | Orders does not import WM |
| `test_work_management_contracts_do_not_reference_order_processing` | WM does not import Orders |
| `test_order_processing_documents_exist_and_are_indexed` | This documentation set |
| `test_contract_inventory_covers_every_schema_definition_and_event` | Inventory coverage |
| `test_workflow_document_lists_every_order_state` | Workflow state coverage |
| `test_domain_separation_document_names_both_bounded_contexts` | Separation coverage |
| `test_execution_plan_references_the_order_processing_issues` | Roadmap coverage |

Related suites: `tests/contracts/test_monorepo_boundaries.py` (domain
separation) and the general contract tests under `tests/contracts/`.

## Commands

```powershell
.venv\Scripts\python.exe scripts\validate_contracts.py
.venv\Scripts\testrunner.exe tests -v --disable-plugin-autoload
pre-commit run --all-files
git diff --check
```

`jsr-testrunner` is the only permitted runner. `pytest`, plugins and
`conftest.py` fixtures are not used in this repository.

## Limitations

- The suite verifies **contracts and documentation**, not runtime behaviour.
  Runtime reliability tests arrive with the services (Issues #50–#54).
- CI targets Python 3.12; local development may run 3.11. The contract
  validators and tests are version-independent, but exact CI reproduction is not
  claimed locally.
- Remote CI status is not verifiable from the local environment and is not
  asserted here.
