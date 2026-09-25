# EventFlow

EventFlow is a distributed, event-driven order processing platform designed to demonstrate production-oriented backend engineering practices.

The project focuses on the engineering challenges found in distributed systems rather than on building a complex e-commerce product.

Its main concerns include:

- Event-driven architecture
- Distributed workflows
- Transactional Outbox Pattern
- Idempotent consumers
- At-least-once message delivery
- Inventory concurrency control
- Failure compensation
- Retry and Dead Letter Queue strategies
- Distributed tracing
- Metrics and structured logging
- Contract-first development
- Automated testing
- CI/CD
- Containerized infrastructure

---

## Architecture

EventFlow is implemented as a monorepo containing independently deployable services.

```text
                         ┌─────────────────┐
                         │     Client      │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   API Gateway   │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Orders Service  │
                         │    FastAPI      │
                         └────────┬────────┘
                                  │
                           PostgreSQL
                                  │
                     Transactional Outbox
                                  │
                                  ▼
                       ┌───────────────────┐
                       │  Redpanda/Kafka   │
                       └─────────┬─────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  │              │              │
                  ▼              ▼              ▼
          ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
          │  Inventory  │ │  Payments   │ │Notification  │
          │ Spring Boot │ │   FastAPI   │ │    Worker    │
          └─────────────┘ └─────────────┘ └──────────────┘

                                 │
                                 ▼
                        OpenTelemetry
                                 │
                  ┌──────────────┼──────────────┐
                  ▼              ▼              ▼
             Prometheus       Grafana       Jaeger/Tempo
```

---

## Services

EventFlow contains five independently executable applications.

| Service | Technology | Responsibility |
|---|---|---|
| `gateway` | Python / FastAPI | Authentication, routing and correlation propagation |
| `orders` | Python / FastAPI | Order lifecycle and distributed workflow orchestration |
| `inventory` | Java / Spring Boot | Stock management, reservations and concurrency control |
| `payments` | Python / FastAPI | Idempotent payment authorization simulation |
| `notifications` | Python | Asynchronous notification processing |

Each service owns its data and is responsible for its persistence model.

Direct database access between services is prohibited.

---

## Repository Structure

```text
eventflow/
├── services/
│   ├── gateway/
│   ├── orders/
│   ├── inventory/
│   ├── payments/
│   └── notifications/
│
├── contracts/
│   ├── openapi/
│   ├── asyncapi/
│   └── schemas/
│
├── infrastructure/
│   ├── docker/
│   ├── kubernetes/
│   └── terraform/
│
├── observability/
│   ├── otel/
│   ├── prometheus/
│   └── grafana/
│
├── tests/
│   ├── e2e/
│   ├── contract/
│   └── resilience/
│
├── docs/
│   ├── architecture/
│   └── adr/
│
├── scripts/
├── .github/
│   └── workflows/
│
├── docker-compose.yml
├── Makefile
├── .gitignore
└── README.md
```

---

## Core Engineering Principles

### Contract-First Development

Public APIs and asynchronous messages must be defined before their implementation.

Contracts are stored under:

```text
contracts/
├── openapi/
├── asyncapi/
└── schemas/
```

Breaking changes require explicit contract versioning.

---

### Database Ownership

Each service owns its persistence layer.

A service must never directly query or modify another service's database.

Communication between bounded contexts occurs through:

- HTTP APIs
- asynchronous events
- explicitly designed read models

---

### Event-Driven Communication

Redpanda/Kafka is used as the asynchronous messaging infrastructure.

The system assumes **at-least-once delivery**.

Therefore, consumers must be idempotent.

The architecture must never depend on global exactly-once delivery.

---

### Transactional Outbox

Domain changes and outgoing events are persisted in the same local database transaction.

```text
Business transaction
        │
        ├── Domain changes
        │
        └── Outbox event
                │
             COMMIT
                │
                ▼
         Outbox Publisher
                │
                ▼
          Redpanda/Kafka
```

This prevents the database/broker dual-write problem.

---

### Idempotency

Commands that create persistent effects must support idempotent processing where applicable.

Examples include:

- order creation
- stock reservation
- payment authorization
- event consumption
- compensation operations

Duplicate message delivery must not generate duplicate business effects.

---

### Failure Compensation

EventFlow does not use distributed database transactions.

Failures are handled using explicit business compensation.

Example:

```text
Order Created
      │
      ▼
Stock Reserved
      │
      ▼
Payment Requested
      │
      ├── APPROVED ──► Order Confirmed
      │
      └── DECLINED
              │
              ▼
      Release Inventory
              │
              ▼
       Order Cancelled
```

---

## Order Lifecycle

The initial order state machine is:

```text
PENDING
   │
   ▼
STOCK_RESERVED
   │
   ▼
PAYMENT_PROCESSING
   │
   ▼
CONFIRMED
```

Failure paths may transition through:

```text
PENDING
   │
   └──────────────► CANCELLED

STOCK_RESERVED
   │
   ▼
CANCELLING
   │
   ▼
CANCELLED

PAYMENT_PROCESSING
   │
   ▼
CANCELLING
   │
   ▼
CANCELLED
```

Invalid state transitions must be rejected by the domain.

---

## Event Envelope

All domain events use a common envelope.

Example:

```json
{
  "event_id": "uuid",
  "event_type": "order.created",
  "schema_version": 1,
  "occurred_at": "2026-09-25T16:00:00Z",
  "producer": "orders-service",
  "correlation_id": "uuid",
  "causation_id": null,
  "aggregate_type": "order",
  "aggregate_id": "uuid",
  "payload": {}
}
```

Every event must be independently identifiable and traceable.

---

## Main Events

Initial event contracts include:

```text
order.created
inventory.reserved
inventory.rejected
payment.requested
payment.approved
payment.declined
inventory.release.requested
inventory.released
order.confirmed
order.cancelled
```

Schemas are maintained under:

```text
contracts/schemas/
```

---

## Observability

Observability is part of the architecture and not an optional production enhancement.

EventFlow uses OpenTelemetry for instrumentation.

The platform should provide:

- distributed tracing
- structured logs
- application metrics
- infrastructure metrics
- consumer metrics
- outbox monitoring
- DLQ monitoring

The observability stack includes:

```text
OpenTelemetry
Prometheus
Grafana
Jaeger/Tempo
```

Business correlation and technical tracing are treated separately:

```text
correlation_id -> business workflow correlation
trace_id       -> distributed technical execution
event_id       -> individual event identity
```

---

## Testing Strategy

The project uses multiple testing levels.

```text
Unit Tests
    │
    ▼
Integration Tests
    │
    ▼
Contract Tests
    │
    ▼
End-to-End Tests
    │
    ▼
Resilience Tests
```

Critical scenarios include:

- successful order processing
- duplicate HTTP commands
- duplicate event delivery
- concurrent inventory reservations
- insufficient inventory
- payment rejection
- compensation
- broker outage
- consumer restart
- event replay
- DLQ handling

A successful happy path alone is not considered sufficient.

---

## Infrastructure

The local environment is orchestrated through Docker Compose.

Expected infrastructure includes:

```text
PostgreSQL
Redpanda
OpenTelemetry Collector
Prometheus
Grafana
Jaeger/Tempo
```

Kubernetes and Helm deployment will be introduced after the local distributed workflow is stable.

---

## CI/CD

Pull requests are expected to execute:

```text
Lint
  ↓
Static Analysis
  ↓
Type Checking
  ↓
Unit Tests
  ↓
Integration Tests
  ↓
Contract Validation
  ↓
Container Build
  ↓
Security Scan
```

The `main` branch must remain deployable.

---

## Architecture Decision Records

Architectural decisions are documented under:

```text
docs/adr/
```

Initial ADRs include:

```text
ADR-001 - Microservices architecture
ADR-002 - Kafka-compatible event streaming
ADR-003 - Transactional Outbox
ADR-004 - Order workflow orchestration
ADR-005 - Inventory concurrency strategy
ADR-006 - Event versioning
ADR-007 - OpenTelemetry
ADR-008 - Monorepo strategy
```

---

## Development Status

EventFlow is currently under active development.

Current phase:

```text
Phase 0 - Architecture and contracts
```

Implementation order:

```text
Architecture
    ↓
ADRs
    ↓
OpenAPI
    ↓
AsyncAPI
    ↓
Event Schemas
    ↓
Domain Tests
    ↓
Domain Implementation
    ↓
Infrastructure
```

Framework implementation must not precede the definition of the relevant contracts and domain behavior.

---

## Requirements

Development requirements will evolve with the project.

Expected baseline:

- Git
- Docker
- Docker Compose
- Python
- Java 21+
- Maven
- GNU Make or compatible environment

Individual services may define additional requirements.

---

## Running the Project

The project is not yet runnable as a complete distributed system.

Once the initial infrastructure is implemented, the expected development workflow will be:

```bash
make up
```

Tests:

```bash
make test
```

Shutdown:

```bash
make down
```

These commands become contractual only after their corresponding implementation is merged.

---

## Documentation

Technical documentation is maintained alongside the source code.

```text
docs/
├── architecture/
└── adr/
```

API and event contracts are maintained separately:

```text
contracts/
├── openapi/
├── asyncapi/
└── schemas/
```

Documentation changes are expected whenever an architectural decision or public contract changes.

---

## License

This project is licensed under the MIT License.

See the [LICENSE](LICENSE) file for details.
