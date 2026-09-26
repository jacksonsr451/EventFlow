# Transactional Outbox

Transactional Outbox stores an outgoing event in the same local database
transaction as the domain change that caused it. A separate publisher later
reads pending rows and sends them to the broker.

This controls the database/broker dual-write gap. It does not make the broker
part of the database transaction and does not provide exactly-once end to end.
Publishers must tolerate crashes, retries and concurrent row claiming.

Useful signals include pending count, oldest pending age, publish rate,
failures and retries. Multiple publishers may claim distinct rows or batches;
the exclusive unit is the row/batch, not the whole publisher. `SKIP LOCKED`
is a possible PostgreSQL strategy, not a mandatory implementation. Recovery
should use bounded batches, limited concurrency and backpressure rather than
an uncontrolled surge. Permanent failures retain the original event and
diagnostic metadata and go through the documented DLQ/reprocessing process.

See [ADR-003](../adr/ADR-003-transactional-outbox.md).
