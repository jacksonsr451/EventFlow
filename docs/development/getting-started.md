# Getting Started

The repository is currently in Phase 0. The service directories and local
infrastructure described by the architecture are not implemented yet. The
first machine-readable contract baseline exists under `contracts/`.
`docker-compose.yml`, `Makefile` and the service directories therefore do not
provide a runnable distributed system today.

The intended sequence is architecture, contracts, domain tests, service
implementation and infrastructure. Do not treat `make up` or `make test` as
available commands until their implementations exist.

Future contributors will need Python, Java and Go toolchains for the planned
services. Exact language versions are not formally decided here. Each service
may have its own toolchain and dependency management, while contracts,
observability and reliability conventions remain shared at the system level.
