# Webapp Development

The EventFlow webapp lives in `clients/webapp`. It is a Vite React application
that consumes the Work Management API through the shared packages under
`packages/`; it does not import backend service code.

## Prerequisites

- Node.js 22 or newer
- pnpm 11.0.8, as declared by the repository `packageManager` field
- The Work Management API at `http://localhost:8000` for live development

Install dependencies from the repository root:

```text
pnpm install --ignore-scripts
```

The `--ignore-scripts` flag is useful in environments where pnpm build scripts
are approval-gated. It is also used by CI; Vite, TypeScript, and Playwright do
not require project postinstall hooks to run the application tests.

## Local Development

Start the Vite development server:

```text
pnpm dev
```

The app is served at `http://localhost:5173`. Vite proxies `/v1` requests to
`http://localhost:8000`; set `EVENTFLOW_API_PROXY_TARGET` to override the
development API target. `VITE_API_BASE_URL` can be set when the API is hosted
on another origin, but that deployment must configure credentials-enabled CORS.

The backend's default web authentication redirect is
`http://localhost:5173/auth/complete`. Login uses the BFF OIDC redirect and
HTTP-only session cookie. The browser does not store access or refresh tokens.

## Package Boundaries

- `packages/domain`: generated Work Management OpenAPI types and domain aliases.
- `packages/api-client`: typed fetch client, RFC 9457 problem mapping, CSRF,
  correlation IDs, ETags, idempotency headers, and query-key factories.
- `packages/ui`: semantic design tokens, light/dark theme variables, and
  accessible Radix-backed primitives.
- `clients/webapp`: routing, providers, workspace/project context, pages, and
  browser-specific behavior.

The UI keeps CSRF state in memory. Unsafe requests include the CSRF header when
the session endpoint provides a token. A central 401 handler clears the memory
token and sends the user to `/login?expired=1` without creating redirect loops.

## Validation

Run the same checks used by the frontend CI job:

```text
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm --filter @eventflow/webapp exec playwright install chromium
pnpm test:e2e
```

Unit tests use Vitest, React Testing Library, MSW, and axe-core. Playwright
tests intercept the session and Work Management routes, so ordinary CI does
not require a running Keycloak instance or a real identity-provider login.

## Real Integration Browser Test

The real browser flow is opt-in and separate from deterministic CI. Start
PostgreSQL and Keycloak with the authentication bootstrap, start the BFF on
`http://127.0.0.1:8000` with the generated local environment, then run:

```text
$env:EVENTFLOW_REAL_E2E = "1"
$env:EVENTFLOW_TEST_KEYCLOAK_USERNAME = "<local test username>"
$env:EVENTFLOW_TEST_KEYCLOAK_PASSWORD = "<local test password>"
pnpm --filter @eventflow/webapp test:e2e:real
```

This test performs the real OIDC login, verifies the HttpOnly session cookie,
reloads the authenticated application, and logs out. It is not part of the
ordinary PR checks because those checks do not provision identity-provider
credentials.

## API Boundaries

The current Work Management contract intentionally limits some views:

- Proposals are loaded per consultation; there is no workspace-wide proposals
  endpoint.
- Consultations and work items do not expose a `project_id` list filter.
- Boards can be filtered by project.
- The dashboard avoids inventing totals from partial paginated responses and
  displays honest empty, unavailable, forbidden, and retry states.

When a page needs a capability not represented in the OpenAPI contract, extend
the contract and API client first. Do not add a browser-only endpoint or infer
server-side totals from an incomplete page.
