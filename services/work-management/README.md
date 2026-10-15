# Work Management service

Python/FastAPI bounded-context service for Work Management (ADR-007). This
directory currently implements the **persistence foundation**: SQLAlchemy 2.x
models, Alembic migrations, repository units of work and deterministic seeds,
per [ADR-008](../../docs/adr/ADR-008-work-management-persistence.md). The HTTP
API, authentication and RBAC are owned by other issues and are not implemented
here.

## Layout

```
services/work-management/
├── alembic.ini
├── pyproject.toml
└── src/eventflow_work_management/
    ├── config.py            # environment-driven configuration
    ├── db/                  # declarative base, engine, session, health
    ├── models/              # one module per aggregate/table
    ├── repositories/        # transaction-scoped units of work
    ├── seeds/               # deterministic development data
    └── migrations/          # Alembic environment and versions
```

## Configuration

All configuration comes from the environment; no credentials are committed.

- `EVENTFLOW_DATABASE_URL` — PostgreSQL URL using the `postgresql+psycopg`
  dialect.
- `EVENTFLOW_TEST_DATABASE_URL` — admin database used by integration tests to
  create and drop throwaway databases.

See the repository [`.env.example`](../../.env.example). Local PostgreSQL is
provided by the root [`docker-compose.yml`](../../docker-compose.yml):

```bash
docker compose up -d postgres
export EVENTFLOW_DATABASE_URL="postgresql+psycopg://eventflow:<password>@localhost:5432/eventflow"
alembic -c services/work-management/alembic.ini upgrade head
```

## Tests

The service uses `jsr-testrunner` (never pytest). Integration tests require a
reachable PostgreSQL instance and skip themselves when
`EVENTFLOW_TEST_DATABASE_URL` is not set.

```bash
testrunner services/work-management/tests -v --disable-plugin-autoload
```

## Boundaries

- This service never reads or writes Order Processing tables or contracts
  (ADR-006, ADR-008).
- User identifiers are stored as UUIDs without foreign keys until the identity
  store exists ([Issue #9](https://github.com/jacksonsr451/EventFlow/issues/9),
  [Issue #10](https://github.com/jacksonsr451/EventFlow/issues/10)).
