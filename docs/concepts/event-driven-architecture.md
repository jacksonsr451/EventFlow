# Event-Driven Architecture

An event records that something happened; a command asks an owner to perform
work. Event-driven communication decouples timing, but introduces eventual
consistency, duplicate delivery and delayed failure visibility.

In EventFlow, asynchronous events coordinate the Order Saga. HTTP remains
appropriate for immediate reads or responses. Events use a standard envelope;
the first machine-readable contracts are under `contracts/`. Events do not
transfer data ownership.

See [at-least-once delivery](at-least-once-delivery.md),
[idempotency](idempotency.md) and [Transactional Outbox](transactional-outbox.md).
