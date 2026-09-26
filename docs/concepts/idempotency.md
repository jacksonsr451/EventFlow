# Idempotency

Idempotency means that processing the same operation again does not create an
additional business effect. It is required because messages and client
requests can be retried.

Transport deduplication uses `consumer_name` plus `event_id` in an Inbox or
`processed_messages` record. Business idempotency uses an operation identity
such as `payment_id`, `refund_id`, `compensation_id` or `reservation_id`.
These mechanisms are complementary: a new `event_id` can carry the same
business operation.

When applicable, Inbox insertion, domain change and the next Outbox insertion
belong to one local transaction. The `(consumer_name, event_id)` pair is the
deduplication key. A broker offset is acknowledged only after that local
transaction succeeds; a failed transaction remains retryable or follows the
consumer's DLQ policy. Future tests must cover duplicate events, release and
financial compensation and duplicate notification delivery. For Notifications,
`source_event_id` plus a stable notification operation identity can prevent
duplicate local work. When an external provider supports an idempotency key,
the same stable key should be reused across retries; local deduplication cannot
undo a provider side effect that happened before a process crash.
