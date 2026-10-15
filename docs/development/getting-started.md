# Getting Started

The repository is currently in Phase 0. Most service directories and local
infrastructure described by the architecture are not implemented yet. The first
machine-readable contract baseline exists under `contracts/`, and the Work
Management service has its PostgreSQL persistence foundation
([ADR-008](../adr/ADR-008-work-management-persistence.md)). `docker-compose.yml`
today provides only the local PostgreSQL instance, and `Makefile` is still
empty, so the repository does not provide a runnable distributed system.

The intended sequence is architecture, contracts, domain tests, service
implementation and infrastructure. Do not treat `make up` or `make test` as
available commands until their implementations exist.

Future contributors will need Python, Java and Go toolchains for the planned
services. Exact language versions are not formally decided here. Each service
may have its own toolchain and dependency management, while contracts,
observability and reliability conventions remain shared at the system level.

## Contract Validation

The current CI validates the contract baseline only. It uses Python 3.12 and
Node.js 22 on GitHub-hosted Linux runners. Run the same local checks with the
pinned tooling below:

```text
python -m pip install "PyYAML==6.0.3" "jsonschema==4.26.0" "jsonschema-specifications==2025.9.1" "referencing==0.37.0" "openapi-spec-validator==0.9.0"
python scripts/validate_contracts.py
openapi-spec-validator contracts/openapi/orders.yaml
npx --yes @asyncapi/cli@6.2.0 validate contracts/asyncapi/workflow.yaml
```

The AsyncAPI command additionally requires Node.js and npm; they are not
needed for the pre-commit hooks themselves.

## Work Management Persistence

The Work Management persistence foundation runs against PostgreSQL. Copy
`.env.example` to `.env`, set local values, start the database, and apply the
migrations:

```text
docker compose up -d postgres
python -m pip install "SQLAlchemy==2.0.54" "alembic==1.20.0" "psycopg[binary]==3.3.6" "PyYAML==6.0.3" "jsr-testrunner==0.1.0"
alembic -c services/work-management/alembic.ini upgrade head
testrunner services/work-management/tests -v --disable-plugin-autoload
```

The integration tests create and drop their own throwaway databases and read the
admin URL from `EVENTFLOW_TEST_DATABASE_URL`; they skip themselves when it is not
set. See
[work-management-persistence.md](../architecture/work-management-persistence.md).

Service tests for other services, container builds and Continuous Deployment
will be added only after corresponding implementations and deployable
environments exist.

## Pre-commit

Pre-commit provides fast local checks before a commit; CI remains the
authoritative validation. Python 3.10 or newer is required. Install the pinned
framework and the already documented contract-tooling dependencies in the same
Python environment, then enable and run the hooks:

```text
python -m pip install "pre-commit==4.6.2" "PyYAML==6.0.3" "jsonschema==4.26.0" "jsonschema-specifications==2025.9.1" "referencing==0.37.0"
python -m pre_commit install
python -m pre_commit run --all-files
```

The configuration uses the pinned `pre-commit-hooks` `v6.0.0` release. The
full OpenAPI and AsyncAPI validators remain in CI rather than downloading npm
tooling during every commit. Update hook revisions deliberately with
`pre-commit autoupdate --freeze` and review the resulting configuration changes.
The whitespace and EOF hooks may modify files; review and stage those fixes
before committing.
