# Development Conventions

- Treat architecture documents as planned behavior unless implementation
  evidence is explicitly cited.
- Preserve exclusive data ownership; never use another service's tables.
- Use `Order`, `Cart`, `Reservation`, `PriceQuote`, `Saga`, `Outbox` and
  `Inbox` consistently.
- Distinguish `event_id`, business operation IDs, `correlation_id`,
  `causation_id`, `trace_id` and `span_id`.
- Keep domain failures separate from transient technical failures.
- Version incompatible event contracts and retire old versions only with
  evidence.
- Add structured logs, metrics and traces without high-cardinality metric
  labels.
- Keep service implementations independent of contract language: Python,
  Java and Go types must not leak into OpenAPI, AsyncAPI or JSON Schema.
- For Go services, use `context.Context` for cancellation and deadlines where
  relevant, not as general-purpose domain storage. Prefer bounded concurrency,
  backpressure and graceful shutdown based on concrete operational needs.
- Update documentation when an architectural decision or public contract
  changes.
