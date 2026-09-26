# At-Least-Once Delivery

At-least-once delivery means a message may be delivered multiple times. It
helps avoid silent loss, but does not provide exactly-once business effects.

Outbox publication can duplicate an event after a publisher crash. Consumers
combine Inbox/event deduplication with business operation idempotency. Invalid
messages should not receive useless technical retries; transient failures use
bounded exponential backoff and jitter. Legitimate business outcomes such as
payment decline are not technical retry failures.

This applies to Notifications as well. An `order.confirmed` event may be
redelivered after a consumer or provider failure. Inbox deduplication and a
stable business operation identity reduce duplicate processing, but a provider
side effect can still be duplicated if the provider accepted it before the
consumer recorded success. Exactly-once external notification delivery is not
guaranteed.
