# Saga and Compensation

A Saga coordinates local transactions across services. Compensation is a new
business transaction that neutralizes a previously confirmed effect; it is
not a distributed rollback.

Orders coordinates the workflow. Inventory releases its own Reservation.
Payments decides whether an authorization is voided or a capture is refunded
based on authoritative financial state. A timeout can leave payment unknown
and must trigger reconciliation, not an automatic decline.

An Order remains `CANCELLING` until mandatory compensations complete. A late
financial approval or charge is compensated and never resurrects a cancelled
Order.
