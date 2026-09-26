# ADR-005: Polyglot Service Architecture

## Status

Accepted

## Context

EventFlow is a distributed-systems education and portfolio project. Its
services have different responsibilities and the project intentionally studies
interoperability, observability and failure handling across heterogeneous
runtimes. This adds cost and is not automatically an operational advantage.

Notifications is an asynchronous, I/O-bound event consumer that may integrate
with multiple notification providers. It is also a useful bounded context for
studying controlled concurrency, cancellation, timeouts, graceful shutdown and
backpressure in Go without creating an artificial service.

## Decision

Use the following planned runtime assignments:

- Python/FastAPI: Gateway, Orders and Payments.
- Java/Spring Boot: Inventory.
- Go: Notifications.

Contracts remain independent of implementation language. OpenAPI, AsyncAPI,
JSON Schema and the common event envelope must not depend on Python classes,
Java records, Go structs or proprietary serialization.

Notifications may use goroutines, channels, bounded worker pools and
`context.Context` only when concrete processing, cancellation or integration
needs justify them. Concurrency must be bounded and provider-aware. This ADR
does not claim that all Go mechanisms are required or that Go is universally
faster.

## Consequences

### Positive

- Practical interoperability across Python, Java and Go.
- Cross-runtime contracts and distributed observability become explicit.
- Different runtime and concurrency models can be studied in realistic
  service responsibilities.
- Notifications has a coherent reason to use Go rather than a technology-only
  demonstration.

### Negative

- More toolchains, build pipelines and dependency-management practices.
- Different testing conventions and container/runtime concerns.
- Higher cognitive and maintenance cost.
- Observability and reliability conventions must work across runtimes.
- Contract discipline becomes more important.

## Alternatives Considered

- All services in Python: fewer toolchains, but less practical study of
  cross-runtime interoperability.
- Python and Java only: preserves two runtimes but does not provide the chosen
  Go context for Notifications.
- Add a new artificial Go service only to diversify the stack: rejected; Go is
  assigned to the existing Notifications responsibility.

## Notes

This is an architectural decision, not evidence that any runtime or service is
implemented. See [service responsibilities](../architecture/services.md) and
[communication](../architecture/communication.md).
