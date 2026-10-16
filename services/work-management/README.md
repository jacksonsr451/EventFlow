# Work Management service

Python/FastAPI bounded-context service for Work Management (ADR-007). This
directory implements the SQLAlchemy 2.x persistence foundation, Alembic
migrations, repository units of work, deterministic seeds and the Issue #10
authentication boundary: Keycloak OIDC validation, BFF sessions and trusted
principal resolution. Workspace RBAC belongs to Issue #9; Work Management
business workflow HTTP handlers are not implemented here.

## Layout

```
services/work-management/
├── alembic.ini
├── pyproject.toml
└── src/eventflow_work_management/
    ├── api/                  # FastAPI authentication/session routes and dependencies
    ├── config.py            # environment-driven configuration
    ├── db/                  # declarative base, engine, session, health
    ├── models/              # one module per aggregate/table
    ├── repositories/        # transaction-scoped units of work
    ├── security/             # OIDC, JWT validation, principal and sessions
    ├── seeds/               # deterministic development data
    └── migrations/          # Alembic environment and versions
```

## Configuration

All configuration comes from the environment; no credentials are committed.

- `EVENTFLOW_DATABASE_URL` — PostgreSQL URL using the `postgresql+psycopg`
  dialect.
- `EVENTFLOW_TEST_DATABASE_URL` — admin database used by integration tests to
  create and drop throwaway databases.
- `EVENTFLOW_OIDC_ISSUER`, client IDs, callback URI and CORS origins — Keycloak
  OIDC configuration; production issuer and redirects must use HTTPS.
- `EVENTFLOW_TOKEN_ENCRYPTION_KEYS` — comma-separated Fernet key ring. The first
  key encrypts new session secrets; prior keys remain temporarily for decrypting
  existing rows during rotation.

See the repository [`.env.example`](../../.env.example). Local PostgreSQL is
provided by the root [`docker-compose.yml`](../../docker-compose.yml):

```bash
docker compose up -d postgres
export EVENTFLOW_DATABASE_URL="postgresql+psycopg://eventflow:<password>@localhost:5432/eventflow"
alembic -c services/work-management/alembic.ini upgrade head
```

## Reproducible local authentication environment

The checked-in `infra/keycloak/realm-eventflow-test.json` contains the complete
non-sensitive development realm: the Web BFF, Desktop and VS Code public
clients; redirect allowlists; web origins; PKCE S256; API audience scope and
mapper; token lifetime; and refresh/session policies. No client secrets, user
passwords, or private keys are part of that file. Roles and groups are not
required by the Issue #10 identity boundary; authorization remains Issue #9.

### Prerequisites

- Windows 10/11 with Docker Desktop running in Linux-container mode and Docker
  Compose v2 (`docker compose`).
- Python 3.11+ and Poetry, with the Work Management dependencies installed.
- PowerShell 5.1 or PowerShell 7.

### First run (Windows PowerShell)

Run from the repository root. The bootstrap creates
`.local-data/authentication-test.env` from the secret-free
`.env.example` if the local file is absent.
If it already exists, its contents and credentials are preserved; the bootstrap
uses it without rewriting it.

```powershell
poetry -C services/work-management install
poetry -C services/work-management run python ../../scripts/prepare_auth_test_environment.py
. .\scripts\Use-AuthTestEnvironment.ps1
```

When the shared file is absent, bootstrap generates a unique development test
identity, random Keycloak administrator/test-user/PostgreSQL passwords, and a
Fernet key. It starts PostgreSQL and Keycloak in a dedicated Compose project,
waits for health checks, and verifies realm policies, all three public clients,
redirect allowlists, PKCE S256, the API audience mapper/default scope, and the
enabled test identity through Keycloak's admin API. If the file already exists,
bootstrap preserves its bytes and credentials, uses the versioned realm source,
and does not restart PostgreSQL for legacy shared settings. Repeating bootstrap
does not rotate credentials. Setup errors do not dump Compose output or secret
values.

The reusable, version-controlled realm configuration is at
`infra/keycloak/realm-eventflow-test.json`; Compose and bootstrap import this
file directly. Generated values are stored in the ignored shared file
`.local-data/authentication-test.env`:

- It contains generated admin/test-user/database credentials, OIDC settings,
  ports, Compose project name, and Fernet encryption key when bootstrap creates
  it from the versioned example.
- The bootstrap creates the test identity through Keycloak's admin API. It does
  not consume a realm copy from `.local-data/keycloak/`.
- PostgreSQL data — a project-scoped Docker volume, not a repository file.

To load the generated settings into a new PowerShell session, dot-source
`. .\scripts\Use-AuthTestEnvironment.ps1`; it does not display secret values.
The default Keycloak and PostgreSQL ports are `8082` and `5432`. The ignored
`.local-data/keycloak/` directory and any pre-existing files there are left
untouched.

### Run integration and regression tests

After dot-sourcing the environment helper, run:

```powershell
$env:PYTHONPATH = "src"
Push-Location services/work-management
poetry run testrunner tests -v --disable-plugin-autoload
Pop-Location
```

The real Keycloak test drives Authorization Code + PKCE through login, verifies
the API audience in the access token, checks session/refresh/logout behavior,
and rejects callback replay. The suite also runs the PostgreSQL persistence and
migration checks. Root contract validation is `python scripts/validate_contracts.py`;
the client adapter tests are `node --experimental-strip-types --test packages/auth/tests/*.test.mjs`.

### Stop or reset

Stop the stack while keeping local credentials/configuration:

```powershell
poetry -C services/work-management run python ../../scripts/prepare_auth_test_environment.py --stop --volumes
```

`--volumes` is available for a database volume created by a fresh bootstrap;
the script refuses to remove volumes when using a pre-existing shared
configuration. Run the first-run bootstrap command again to recreate the local
stack. It reuses the saved local credentials. Do not copy or commit generated
files. `.local-data/` remains git-ignored.

### Troubleshooting and security

- If Docker is unavailable, start Docker Desktop and confirm `docker info` and
  `docker compose version` work.
- If a port is occupied before first setup, choose unused ports and a project
  name with `--keycloak-port 8182 --postgres-port 55432 --project-name eventflow-auth-alt`.
  Use those same options on later runs; the bootstrap rejects conflicting
  settings rather than silently changing a live environment.
- If the realm/client verification fails, stop the isolated stack with
  `--stop --volumes`, then bootstrap again. Inspect Docker health with
  `docker compose --project-name eventflow-auth-dev --env-file .local-data/authentication-test.env --profile auth ps`.
- Ensure the shell running tests has the environment loaded by dot-sourcing
  `Use-AuthTestEnvironment.ps1`; tests otherwise skip the real Keycloak flow.
- This profile uses Keycloak `start-dev`, HTTP, a generated administrator, and
  loopback-only ports. It is for local development/testing only: do not expose
  it to a network, reuse its credentials in another environment, or use its
  HTTP/realm settings in production.

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
