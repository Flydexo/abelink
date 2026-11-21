# Agent instructions

These instructions apply to the entire repository. Read
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) before deployment, DNS, server,
GitHub integration, secrets, or maintenance work.

## Repository

- Repository: `Flydexo/abelink`. Treat this as the monorepo root, but inspect
  the actual tree before assuming an `apps/` directory or workspace tooling.
- Currently the only deployable app is the root Vite/React landing page.
  `docker-compose.yml` builds service `web` using the root `Dockerfile`.
- Install with `npm ci`; validate frontend changes with `npm run build`.
  No test or lint script currently exists. Do not invent successful checks.
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
