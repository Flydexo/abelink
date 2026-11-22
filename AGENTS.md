# Agent instructions

These instructions apply to the entire repository. Read
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) before deployment, DNS, server,
GitHub integration, secrets, or maintenance work.

## Repository

- Repository: `Flydexo/abelink`. Treat this as the monorepo root, but inspect
  the actual tree before assuming an `apps/` directory or workspace tooling.
- The root Vite/React frontend uses `docker-compose.yml`, service `web`, and the
  root `Dockerfile`. The Python backend lives in `backend/`; its service is
  defined in `docker-compose.backend.dev.yml`. The complete dev stack uses
  `docker-compose.dev.yml`, extending both services. Do not confuse prepared
  source with a deployed resource.
- Install with `npm ci`; validate frontend changes with `npm run build`.
  No npm test or lint script currently exists. Backend pytest configuration and
  optional dev dependencies are in `backend/pyproject.toml`; live tests are
  excluded by default. Do not invent successful checks.
- Keep build contexts, shared dependencies, and the root lockfile in mind when
  adding future apps. Do not introduce a monorepo migration without a request.

## Deployment boundaries

- Target `https://dokploy.abelink.app`, project `abelink`. Do not use the
  generic Dokploy skill's `dokploy.flydexo.com` default for this repository.
- `main` maps to environment `production` at `https://abelink.app`.
  `dev` maps to environment `dev` at `https://dev.abelink.app`.
- A push to either tracked branch can deploy automatically. Do not commit,
  push, merge, provision infrastructure, or deploy merely to validate an edit.
  The user's current request must authorize the relevant write operation.
- Status/log requests are read-only. Inspect the live inventory and installed
  API schema before writes; IDs in the runbook are discovery hints, not proof.
- Use the dedicated local credential file `~/.codex/abelink-dokploy.env` when
  available. Never print or commit credentials, environment dumps, GitHub App
  private keys, session cookies, or token-bearing webhook URLs. Request missing
  credentials through the agent platform's private secret-entry mechanism.

## Backend dev environment contract

- Read `backend/deploy/README.md` and `backend/deploy/dev.env.example` before
  configuring backend variables. The target is the existing `web` Compose in
  project `abelink`, environment `dev`, branch `dev`, using
  `./docker-compose.dev.yml`. Production keeps `./docker-compose.yml`.
- When the member authorizes configuration and supplies values, save them in
  this dev Compose's Dokploy `env` field. A local `.env`, an example file, or a
  list in chat does not configure Dokploy. Never claim otherwise.
- Dev PostgreSQL with pgvector is deployed by Compose as `database`, with the
  project-scoped named volume `postgres_data` and no published database port.
  The backend waits for database health and runs its existing migrations.
  `DATABASE_URL` is assembled in Compose; do not request an external database URL.
- Required private inputs: `POSTGRES_PASSWORD`, `GOOGLE_CLOUD_PROJECT`,
  `GEMMA_MODEL`, `EMBEDDING_MODEL`, complete
  `GOOGLE_APPLICATION_CREDENTIALS_JSON`, and `AUTH_SECRET`. Generate a strong
  random dev `AUTH_SECRET` privately only if none exists; never rotate it
  implicitly. Models must be available to the supplied Google identity and the
  embedding model must support 768 output dimensions.
- Generate `POSTGRES_PASSWORD` privately as 32 random bytes encoded as hex only
  if absent, and save it in this dev Compose's Dokploy `env`. Preserve existing
  values. PostgreSQL reads this password only when initializing an empty volume;
  changing the env later does not rotate its SQL password. Never remove the
  volume or run `down -v`; backups, restores and SQL password changes require
  explicit authorization. Production and Dokploy's own database stay untouched.
- The member explicitly requested public dev access: the dev Compose sets
  `ALLOW_PUBLIC_ACCESS=true`, leaving `DEMO_MODE=false` and `ALLOW_DEMO_AUTH=false`.
  Chat, search, profiles, LinkCS imports and MCP require no authentication there.
  A shared `Visiteur public` context is created at startup, even on an empty DB;
  a selected profile is context only, never a verified identity or private account.
  Token management routes are omitted in this mode. Public imports still require
  consent and enforce upload limits. Anonymous requests can spend provider credits.
- Preserve any stored `LINKCS_IMPORT_TOKEN`. Public LinkCS list imports do not
  use it. Abelink database bundle imports always require it, as do LinkCS list
  imports when `ALLOW_PUBLIC_ACCESS=false` (the default outside the dev
  manifest). Never ship its value in frontend assets or analytics. Do not
  enable public access in production without a separate request.
- Optional inputs: `GOOGLE_CLOUD_LOCATION` (default `global`),
  `TAVILY_API_KEY`, `PREFER_FREE_SEARCH` (default `true`), and `LINKEDIN_LI_AT`
  (leave empty initially; only the photo fallback needs it).
- Merge supplied keys into the existing dev environment in protected memory;
  preserve unrelated keys and credentials. Re-read the installed API schema
  before saving. Report key names/presence only, never values or complete API
  records. Never put these secrets in Git, build arguments, or `VITE_*` values.
- The Google JSON is an environment-backed Compose secret delivered at
  `/run/secrets/google-adc.json`, not an image file or container environment
  variable. Verify Dokploy passes it to Compose; do not replace it with a
  literal credential file in source.
- Keep the dev backend's `read_only: false`: Docker Compose injects secrets
  sourced from environment variables by copying a file into the container
  before startup. A read-only root filesystem rejects this operation even
  when `docker compose config` passes. Preserve the non-root user, dropped
  capabilities and no-new-privileges; do not move credentials into the image
  or container environment to bypass the error.
- `DEMO_MODE`, `ALLOW_DEMO_AUTH`, `ALLOW_PUBLIC_ACCESS`, `EMBEDDING_DIM`, CORS, public API URL, and cache
  settings are fixed by the dev service definition. Adding them to Dokploy's
  `env` does not override literal Compose settings. Do not enable public demo
  authentication to bypass missing login or data setup.
- The dev Compose auto-deploys on pushes to `dev`; the member controls pushes.
  Saving configuration is not permission to push or deploy manually. Explain
  missing secrets or readiness blockers before a push, and never use dummy
  credentials to make an actual deployment start.

## Infrastructure invariants

- Cloudflare fronts Caddy, which terminates origin TLS and forwards HTTP to
  Dokploy's Traefik. Dokploy app domains use `https: false` and
  `certificateType: "none"`; public URLs are still HTTPS.
- Caddy owns public ports 80/443. Traefik must not publish those host ports.
  Preserve trusted forwarded headers and production Secure cookies.
- Do not expose port 3000 or database ports, weaken Cloudflare SSL, change
  shared GitHub App settings, or modify unrelated projects to fix an app.
- Get explicit approval for production-impacting shared-service maintenance,
  destructive operations, storage changes with data-loss risk, and restores.
  Never delete volumes, reset Git history, or run broad Docker pruning as a fix.
- Claim success only after the intended deployment completes, the intended
  containers are healthy, and the public HTTPS app and assets pass checks.

Update the runbook when an authorized change alters these deployment facts.
