# CI/CD Strategy

EventFlow separates fast local feedback from authoritative repository
validation. Pre-commit runs small checks before a commit. Pull requests and
pushes to `main` run GitHub Actions. Release and deployment workflows do not
exist yet because there are no deployable services, images, registry or target
environment.

## Current Pipeline

```text
feature branch -> pull request -> CI -> review -> main
```

The current `.github/workflows/ci.yml` has one active `contracts` job. It runs
the repository-quality hooks with the local contract hook skipped, then runs
`scripts/validate_contracts.py` and the pinned OpenAPI and AsyncAPI validators.
It runs on pull requests and pushes to `main`, uses read-only repository
permissions, and cancels obsolete runs for the same PR or branch. GitHub
Actions execution is not implied by local runs; remote status is determined by
the GitHub workflow itself.

Pre-commit remains complementary. Its common hooks and fast contract check are
not a replacement for the CI job or for the official OpenAPI/AsyncAPI checks.
CI reuses the common hooks while explicitly skipping the local contract hook;
the authoritative contract validator runs once through
`scripts/validate_contracts.py`.

## Capability Matrix

| Capability | Pre-commit | PR CI | Main CI | Release | Staging | Production | Status |
|---|---|---|---|---|---|---|---|
| Repository quality | Common hooks | Common hooks plus contract/documentation validation | Same CI workflow | N/A | N/A | N/A | ACTIVE |
| Static contracts | Fast local validator | Full validation | Full validation | Required gate | Required gate | Required gate | ACTIVE |
| Python quality | Not active | Not active | Not active | Gate when present | Gate when present | Gate when present | PLANNED |
| Python unit tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Java quality | Not active | Not active | Not active | Gate when present | Gate when present | Gate when present | PLANNED |
| Java unit tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Go quality | Not active | Not active | Not active | Gate when present | Gate when present | Gate when present | PLANNED |
| Go unit tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Executable contract tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Integration tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Resilience tests | None | None | None | Gate when present | Gate when present | Gate when present | PLANNED |
| Security scanning | Private-key hook | Private-key hook only | Private-key hook only | Required gate | Required gate | Required gate | PARTIAL |
| Dependency scanning | None | Not active | Not active | Required gate | Required gate | Required gate | PLANNED |
| Container build | None | None | None | Build artifact | Promote artifact | Promote artifact | PLANNED |
| SBOM | None | None | None | Generate | Verify/preserve | Verify/preserve | PLANNED |
| Image scanning | None | None | None | Scan before publish | Recheck as needed | Policy gate | PLANNED |
| Artifact signing | None | None | None | Sign | Verify | Verify | PLANNED |
| Artifact publishing | None | None | None | Publish immutable artifact | Promote | Promote | PLANNED |
| Deploy and smoke tests | None | None | None | N/A | Deploy/verify | Deploy/verify | PLANNED |

`PARTIAL` means a narrow repository-level check exists, not that full security
coverage is active. No branch protection or required-check rule is configured
by this repository; the current contract CI is the first candidate for a
required merge check.

## Language Activation

### Python

Activate Python jobs when the first real Gateway, Orders or Payments service
exists and that service owns a project configuration with a pinned Ruff
version. Ruff should provide lint/import checks and formatting checks through
`ruff check` and `ruff format --check`. Type checking is **TO BE DECIDED** and
should be selected after service packaging and typing conventions exist. Pytest
and coverage belong in CI, with thresholds defined only after a real baseline
exists. A matrix for `gateway`, `orders` and `payments` is useful only if their
tooling is sufficiently uniform.

The repository's `scripts/validate_contracts.py` is tooling, not a FastAPI
service. It is intentionally not treated as the first service-quality target.

### Java

Activate Inventory checks only when its real build exists. Maven versus Gradle,
formatter, and static-analysis choices remain with the Inventory build. The
pre-commit layer may call a fast build-owned check; CI should compile, run
analysis and tests, and package using a checked-in, versioned Maven or Gradle
wrapper. CI must not silently fall back to a globally installed build tool.

### Go

Activate Notifications checks only when `go.mod` and Go source code exist.
Pre-commit can run `gofmt` and possibly a fast `go vet`; CI should use
`gofmt -l`, `go vet`, `go test ./...` and, when useful, `go build`. Because
Notifications is concurrent, `go test -race ./...` should be required when the
module and its runtime support make race testing applicable. The module's
`go.mod` toolchain directive, or a future `go.work` policy, will be authoritative.

## Contract And Distributed Tests

Static contract validation is active today. It is not an executable contract
test. Once implementations exist, HTTP tests must exercise implementation
against OpenAPI, and event producer/consumer tests must exercise payloads
against AsyncAPI and JSON Schema.

Integration tests should use disposable PostgreSQL and Kafka/Redpanda
dependencies when enough services exist to execute a real workflow. Future
resilience coverage should include broker/database outages, crashes, duplicate
and delayed delivery, provider timeouts, UNKNOWN payments, Outbox backlog,
retry exhaustion, DLQ behavior and graceful shutdown.

Distributed tests should protect the documented invariants: no overselling,
atomic multi-item reservations, idempotent duplicate effects, valid payment
and reservation requirements for confirmation, complete compensation before
cancellation, stale-event rejection, safe Outbox republication,
reconciliation behavior and Notifications failure isolation.

## Security And Supply Chain

The current private-key hook is a narrow active check in both local pre-commit
and CI. Dependency, broader secret, image and infrastructure scanning are
future gates and must be added only when corresponding manifests or artifacts
exist. Dependency review may be added through an established GitHub mechanism
when dependency manifests and repository permissions make it useful.

The intended future artifact path is:

```text
source -> tests -> build -> container -> SBOM -> scan -> sign -> registry
       -> deploy by immutable digest
```

The registry is **TO BE DECIDED**. Future workflows must use least privilege,
avoid production secrets in pull-request jobs, prefer GitHub Environments and
OIDC when a deployment provider is selected, and never rebuild different code
for production than the artifact that passed validation.

## Release And Deployment

Release strategy is **TO BE DECIDED**. Before activation it must define a
controlled release identity, such as a protected tag or approved release event,
bound to one source commit. The intended sequence is green `main`, release
authorization, immutable artifact creation, staging deployment and
verification, then protected production approval and promotion. No
`release.yml` or `deploy.yml` placeholder is created.

Staging and production are PLANNED. The deployment target, registry,
Kubernetes strategy and Terraform strategy are BLOCKED on concrete platform
decisions and deployable artifacts. CD activation also requires environment
configuration ownership, access controls, observability, smoke-test
infrastructure, backup/recovery expectations, migration gates and event
compatibility evidence. Production should use a protected GitHub Environment,
explicit approval, immutable artifact identity, health/smoke checks and a
documented rollback procedure.

Rollback policy is not operationally defined yet and is a CD activation gate.
It must identify trigger thresholds, decision ownership, environment traffic
handling, asynchronous workflow handling, DLQ/event replay policy and database
forward-fix behavior. The baseline principle is to redeploy a previously
verified application artifact when safe; database rollback must not be assumed.
Service-owned migrations should use backward-compatible expand/contract steps,
with ordering and readiness checks, and never modify another service's tables.
Event deployments must preserve schema-version compatibility, consumer
readiness and coexistence rather than requiring a perfectly simultaneous
deployment. Breaking changes require compatibility evidence before old
versions are removed.

Artifact promotion must carry the same build identity and immutable digest from
release through staging and production; promotion must not rebuild source.
Deployments targeting one environment must be serialized with
`cancel-in-progress: false` or an equivalent environment lock. This is
intentionally separate from cancellation of obsolete PR validation runs.

Production approval policy, including approver ownership, separation of
duties, emergency handling and audit requirements, must be defined before
production activation.

## Environment States

| Environment | Current state | Meaning |
|---|---|---|
| Local | PARTIAL/ACTIVE | Documentation, contracts, scripts and pre-commit can run locally. |
| CI ephemeral | ACTIVE | GitHub-hosted validation runner exists; no service infrastructure is created. |
| Staging | PLANNED/BLOCKED | No target, registry or deployable artifact exists. |
| Production | PLANNED/BLOCKED | No target, environment protection or release process exists. |

The current recommended branch flow is feature branch, pull request, review,
then `main`. Remote branch protection is not configured by this repository.
Deployment concurrency must be designed separately from PR CI concurrency so
an obsolete validation run can be cancelled without cancelling a deployment
that is already acting on an environment.

## Activation Rules

- Python CI starts when a real Python service and its project tooling exist.
- Java CI starts when Inventory has a real Maven or Gradle build.
- Go CI starts when Notifications has `go.mod` and source code.
- Executable contract tests start when a producer or consumer implementation exists.
- Integration and resilience stages start when real services and disposable dependencies can run.
- Container CI starts when the first real Dockerfile exists.
- Release/CD starts when artifacts, a registry, an environment and a deployment target are selected.
- Kubernetes and Terraform checks start only after those artifacts exist.
