# ADR 0001: Modular monolith with hexagonal modules

- Status: Accepted
- Date: 2026-11-02

## Context

AI OS depends on many external systems that will change over time: CRM vendors
(Salesforce, HubSpot, Zoho, in-house), LLM providers, embedding and reranking models,
speech-to-text, telephony and WhatsApp. The business rules (pricing, discount
limits, citation and guardrail rules, context card schema) must stay stable and
testable without any of those systems running.

MVC organizes code by technical role (models, views, controllers). In practice that
spreads one feature across the whole tree and lets infrastructure code leak into
business logic.

## Decision

- **One deployable backend (modular monolith)**, split into modules by bounded context:
  `knowledge`, `inventory`, `pricing`, `crm_copilot`, `interactions`, `coaching`,
  `escalation`, `call_timing`.
- **Each module is hexagonal (ports and adapters):**
  - `domain/`: entities, value objects, pure rules. No IO, no framework imports.
  - `application/`: use cases that orchestrate domain logic through ports.
  - `ports/`: `typing.Protocol` interfaces for anything external.
  - `adapters/`: concrete implementations (Postgres, pgvector, Claude, CRM APIs).
  - `api/`: FastAPI router and HTTP schemas (an inbound adapter).
- **`orchestration/`** holds the LangGraph router and the answer composer. Agents call
  application services as tools; the domain never imports LangGraph.
- **`entrypoints/`** is the only composition root: it wires adapters to ports for
  the API, the Celery worker and the MCP servers.
- **Dependency rule:** `api`/`adapters` → `application` → `domain`. Modules talk to
  each other only through `application` services, never through another module's
  `domain` internals or database tables.

## Consequences

- Swapping a vendor means writing one adapter. Domain and use-case tests don't change.
- Any module (for example `interactions`) can be split into its own service later
  without rewriting it.
- More files than MVC for small features. We accept that cost for testability and
  vendor independence.
- The dependency rule should be enforced in CI (import-linter) once there are
  three or more modules.
