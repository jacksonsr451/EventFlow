# EventFlow Contracts

This directory contains the first machine-readable contract baseline for
EventFlow. Contracts are language-independent and are intended to guide future
tests and service implementations. No service implementation is included here.

## Directories

- `openapi/`: HTTP interfaces used by the current Order and Cart use cases.
- `asyncapi/`: asynchronous workflow channel, messages and delivery metadata.
- `schemas/`: reusable JSON Schema documents for shared values, HTTP models,
  event envelopes and event payloads.
- `examples/`: coherent, non-production examples used to inspect the workflow
  across messages.

## Formats and Compatibility

OpenAPI describes HTTP operations. AsyncAPI describes asynchronous messages.
JSON Schema describes reusable data contracts. Python, Java and Go types must
not leak into these files.

Event schemas use an explicit `schema_version` in the common envelope. Adding
a semantically safe optional field may remain in the same version; consumers
must tolerate unknown fields for that compatibility case. Removing,
renaming, retyping, changing meaning or adding an incompatible required field
requires a new version. Old and new versions may coexist during migration.

HTTP checkout uses `Idempotency-Key`. Repeating the same key and equivalent
request represents the same operation; reusing it with a different request is
an idempotency conflict. The storage and retention mechanism are implementation
concerns.

All workflow messages assume at-least-once delivery. `event_id` identifies one
message, while business operation IDs such as `reservation_id`, `payment_id`
and `compensation_id` identify effects that must remain idempotent. The
workflow partition-key convention is `order_id` where applicable; this does
not provide the Inventory stock invariant.

Monetary values use decimal strings paired with an uppercase three-letter
currency code; binary floating point is not part of the wire contract. The reusable
`Money` object groups `amount` and `currency`, while `PriceQuote` and accepted
Order items retain the documented `unit_price` plus `currency` fields.
Timestamps use RFC 3339 UTC with a `Z` offset. Identifiers use canonical UUID
strings.

## Validation

Contract validation includes YAML/JSON parsing, OpenAPI and AsyncAPI validation,
JSON Schema validation, `$ref` resolution, event-to-schema mapping and example
validation. GitHub Actions runs these checks for pull requests and pushes to
`main`; the local commands are documented in
`docs/development/getting-started.md`.
