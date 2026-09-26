# Distributed Tracing

OpenTelemetry can connect technical work across HTTP handlers, publishers and
consumers. `trace_id` identifies one technical execution and `span_id`
identifies an operation within that trace. `correlation_id` identifies a
long-lived business workflow and may span multiple traces across retries and
asynchronous processing.

Use structured logs, metrics and traces together. Put individual IDs in logs
and traces, not Prometheus labels. Controlled labels include `service`,
`operation`, `result` and `event_type`; `order_id`, `event_id` and `payment_id`
are high-cardinality values.

The same convention applies across Python, Java and Go. Notifications should
propagate relevant correlation and trace context through broker-consume and
provider-call spans when tracing is available; changing runtime must not break
the distributed trace.
