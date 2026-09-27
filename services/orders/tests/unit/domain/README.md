# Orders Domain Unit Tests

This suite is the executable specification for the pure Orders domain. It
covers value objects, the Order aggregate, workflow states, compensation
tracking, idempotent business results, terminal-state protection and the
commercial snapshot. It does not test FastAPI, persistence, brokers, event
envelopes or external service clients.

## Runner

The official runner is `jsr-testrunner`, provided by the `jsr-testrunner`
package. Its installed console command is `testrunner`.

```text
poetry run testrunner --assert=plain tests/unit/domain
```

Discovery follows the runner's pytest-compatible `test_*.py` convention. The
runner supports `--collect-only` for discovery validation and `--cov` through
its coverage plugin. No minimum coverage threshold is defined at this TDD
stage.

## VALID RED

`VALID RED` means collection, syntax and test structure are valid, while test
execution is expected to fail because the Orders domain implementation has not
been created yet. Importing domain types inside test execution keeps missing
domain modules from turning collection into a broken suite. Syntax errors,
invalid fixtures, invalid runner commands or unsupported expectations are not
valid RED.

The development cycle is:

```text
RED -> GREEN -> REFACTOR
```

## Recommended TDD Order

1. Money
2. OrderItem
3. Order creation
4. Inventory reservation
5. Inventory rejection
6. Payment processing
7. Confirmation invariant
8. Cancellation
9. Compensation tracking
10. Terminal states
11. Idempotency
12. Out-of-order results
13. Commercial snapshot
