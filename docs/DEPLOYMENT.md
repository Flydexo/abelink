# Abelink deployment and administration runbook

Audience: agents deploying or maintaining applications in `Flydexo/abelink`.
Baseline inspected **November 21, 2026**, against Dokploy **v0.31.4**.
Re-discover live state before acting; this document does not authorize changes.

## 1. Scope and safety

1. Identify the requested app, environment, branch, and operation. If ambiguous,
   ask before writing. Do not infer permission to deploy from a code-edit request.
2. Inspect repository instructions, `git status`, deployment files, live resource
   inventory, and the installed API schema. Preserve unrelated local edits.
3. Plan the smallest change. Ordinary app deployments must not alter shared
   proxies, global Cloudflare settings, server identity, or another application.
4. Before destructive changes, restores, or shared-service downtime, explain
   impact, backup/recovery steps, and obtain explicit approval.
5. Verify deployment identity, runtime health, and public behavior separately.
   Report anything still queued, building, unhealthy, or unverified honestly.

Never run `docker system prune --volumes`, `docker volume prune`,
`docker compose down -v`, delete/recreate the server or project, force-push a
tracked branch, or overwrite environment settings as a troubleshooting shortcut.
Do not commit or push changes unless the user requests it; pushes can deploy.

## 2. Deployment inventory

IDs and generated names below are lookup hints. Resolve them from the live
project before every write; abort if the target does not match.

| Resource | Baseline |
| --- | --- |
| Repository | `Flydexo/abelink` (private) |
| Dokploy | `https://dokploy.abelink.app` |
| Dokploy project | `abelink`, `g4pFIXTdoJhC0rCK0K0Md` |
| Hetzner server | `abelink-dokploy`, ID `177068188` |
| Compute / OS | CX23, 2 shared vCPU, 4 GB RAM, 40 GB disk; Ubuntu 24.04; `fsn1` |
| IPv4 / SSH | `91.99.156.3`; `root`, authorized SSH key required |
| Hetzner firewall | `abelink-dokploy-fw`; inbound TCP 22, 80, 443 |
| Cloudflare zone | `abelink.app`, `f45e7e336461653dfb4aec6313c3b10c` |
| Public DNS | Proxied A records: `abelink.app`, `dev.abelink.app`, `dokploy.abelink.app` |

| Environment | Source branch | Public URL | Environment ID | Compose ID |
| --- | --- | --- | --- | --- |
| `production` | `main` | `https://abelink.app` | `BlRAh8H-GZBR7l-eQSPzT` | `9qAEn3fJXa3wkFBeX9y66` |
| `dev` | `dev` | `https://dev.abelink.app` | `0uHl09pUSzt7I8_XvrDoR` | `XXp-RthZqER8mcRUd5_HS` |

Dokploy creates a mandatory default environment named `production`; it cannot
be renamed through the installed API. Do not create a third environment named
`main` to work around this. Both environments currently contain Compose `web`:

| Environment | Generated Compose `appName` |
| --- | --- |
| `production` | `compose-navigate-1080p-driver-gigkyz` |
| `dev` | `compose-generate-wireless-program-l3yhh4` |

The initial source revision on both branches was
`87537013458052c0a249acf23059863ed53cb269`; it is historical, not a release pin.

## 3. Repository and build contract

This repository is the intended monorepo root, not an `apps/*` workspace.
The deployed Compose baseline below is the root-level static landing page.
The current checkout also contains a Python backend under `backend/`; its
presence does not mean it has been deployed. See section 12 for the complete
dev-only stack and its auto-deployment configuration.

- `package.json` / `package-lock.json`: npm dependency source of truth.
- `src/`: React application; Vite builds to `dist/`.
- `Dockerfile`: Node 24 Alpine build stage, then nginx serving static assets.
- `nginx.conf`: internal HTTP port 80, SPA fallback, immutable hashed assets.
- `docker-compose.yml`: `web`, `build: .`, restart policy, internal port 80.
- Image health check: HTTP GET `/` inside the container every 30 seconds.
- For the frontend-only baseline, no application database, persistent app volume, or required app secret is
  declared by the current Compose file. Dokploy itself does have persistent state.

Local validation after relevant code changes:

```bash
npm ci
npm run build
docker compose config --quiet
docker compose build web
```

Run the Docker commands only where Docker is available. No test/lint script is
currently configured. Building locally does not deploy unpublished source.
The Compose service exposes its port to Docker networks; it does not publish
localhost port 80. Use `npm run dev` for the local frontend, or arrange an
explicit temporary port mapping when container-level testing is needed.

`VITE_*` values are public build-time configuration, not secrets. Adding an
environment value to Dokploy does not automatically provide a Docker build
argument or inject it into a service. Configure the actual build/runtime path.

## 4. Credentials and API discovery

### Credential routing

This project uses its **own** Dokploy instance, not `dokploy.flydexo.com`.
The generic deployment skill's default target/token can belong to that other
instance. Never silently substitute them.

On the provisioning workstation, the dedicated private file is
`~/.codex/abelink-dokploy.env`, containing `DOKPLOY_URL` and
`DOKPLOY_API_TOKEN`. It is outside Git and must remain mode 600. Load it only
when needed, in a dedicated shell/process with tracing disabled:

```bash
set +x
set -a
source "$HOME/.codex/abelink-dokploy.env"
set +a
test "$DOKPLOY_URL" = 'https://dokploy.abelink.app' || exit 1
```

Source only a trusted local credential file. If unavailable, use an already
authorized connection to this instance or request a credential through private
secret entry. Never ask for a token in chat or use a placeholder. Do not print
the file, environment, raw API configuration records, or HTTP auth headers.
API authentication uses `x-api-key`, not an assumed bearer scheme.

### Safe read-only discovery example

Run after loading the dedicated credentials. The allowlist deliberately omits
environment documents, provider secrets, and webhook tokens from its output.

```bash
node --input-type=module <<'JS'
const base = process.env.DOKPLOY_URL;
if (base !== 'https://dokploy.abelink.app') throw new Error('Wrong instance');
const headers = { 'x-api-key': process.env.DOKPLOY_API_TOKEN.trim() };
async function read(path) {
  const response = await fetch(`${base}/api/${path}`, { headers });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}
const schema = await read('settings.getOpenApiDocument');
console.log('Installed API:', schema.info.version);
const projects = await read('project.all');
const matches = projects.filter(project => project.name === 'abelink');
if (matches.length !== 1) throw new Error('Project missing or ambiguous');
const project = matches[0];
for (const environment of project.environments) {
  for (const service of environment.compose) {
    const compose = await read(`compose.one?composeId=${encodeURIComponent(service.composeId)}`);
    console.log({
      projectId: project.projectId,
      environment: environment.name,
      environmentId: environment.environmentId,
      composeId: compose.composeId,
      appName: compose.appName,
      branch: compose.branch,
      sourceType: compose.sourceType,
      composePath: compose.composePath,
      autoDeploy: compose.autoDeploy,
      status: compose.composeStatus,
    });
  }
}
JS
```

Inspect the relevant operation's parameters and request body in
`GET /api/settings.getOpenApiDocument` before using it. Paths in the schema
omit the `/api` prefix. GET input goes in the query string; POST input is JSON.
If a write times out, inspect current configuration/history before retrying.

Verified baseline endpoints; re-check after upgrades:

| Operation | Method / endpoint | Inputs |
| --- | --- | --- |
| Inventory | GET `project.all` | None |
| Resource details | GET `compose.one` | `composeId` |
| Domain inventory | GET `domain.byComposeId` | `composeId` |
| Source/config change | POST `compose.update` | `composeId`, only intended changes |
| Deploy | POST `compose.deploy` | `composeId`, optional title/description |
| Deployment history | GET `deployment.allByCompose` | `composeId` |
| Build/deploy logs | GET `deployment.readLogs` | `deploymentId`, bounded `tail` |
| Container lookup | GET `docker.getContainersByAppNameMatch` | Actual `appName`, `appType: "docker-compose"` |
| Runtime logs | GET `compose.readLogs` | `composeId`, actual `containerId`, `tail`, optional `since` |

Full configuration responses and logs can contain secrets. Keep them private;
summarize or redact instead of pasting them into chat or committing captures.

## 5. Normal deploy and promotion

1. Confirm the app/environment and deployment authorization. Check local edits
   and remote branch state; do not overwrite user work or change branches blindly.
2. Validate the relevant build and Compose configuration. Check whether the
   change affects shared libraries, Docker context, environment values, or data.
3. When a push is authorized, publish to `dev` for development. Verify that
   deployment before promoting the tested change to `main` through the team's
   approved merge workflow. Never merge or push automatically without a request.
4. GitHub push hooks trigger the matching Compose deployment. Both resources
   use GitHub source, `autoDeploy: true`, trigger `push`. Production keeps
   `./docker-compose.yml`; dev uses `./docker-compose.dev.yml` for web + backend + database.
   Confirm live watch paths include every changed app/shared dependency.
5. If the user requests a redeploy without a source change, resolve the Compose
   ID and submit the installed `compose.deploy` operation. Record submission
   time and the returned deployment ID, if any. Do not simultaneously push and
   manually deploy the same revision unless intentional.
6. Follow the matching deployment, not just the latest successful record. When
   submission returns no deployment ID, correlate Compose ID, submission time,
   source revision, and history; a queued response is not a completed deployment.
7. Apply the acceptance checks in section 8. Report the branch/revision and URL.

Redeploying a branch normally builds its current remote head; it is **not** a
rollback to an earlier deployment or a way to publish local uncommitted changes.
Preserve Dokploy's generated command and actual `appName`. The command field
omits the leading `docker`; do not accidentally add a second Docker prefix.

### GitHub integration

The provider reuses the existing authorized Flydexo GitHub App installation.
Do not change that App's global webhook, callback URL, permissions, or private
key merely to maintain this repository; another Dokploy instance also uses it.

Independent repository push hooks point to Dokploy's supported Compose webhook
routes: hook `714866622` for production and `714866625` for dev. Their URLs
contain deployment bearer tokens and must remain private. Do not substitute
the GitHub App webhook endpoint: repository events need not contain the App
installation metadata that endpoint expects.

Check repository hooks and delivery status through authenticated GitHub tools.
Print hook IDs, event names, timestamps, and HTTP statuses, **not** complete
hook configuration URLs. Ping success proves reachability, not branch behavior
or deployment success. A push-event smoke test causes a real redeploy and
requires deployment authorization; do not generate commits merely as a test.

## 6. Adding applications to the monorepo

Keep deployment structure aligned with the actual code rather than imposing
workspace tooling. For each new app, record its source directory, Dockerfile,
build context, dependencies, internal listener, health check, and state needs.

- Prefer extending the existing Git-backed Compose stack with a clearly named
  service when it shares the same release lifecycle. Add a separate Git-backed
  Compose resource per environment when independent releases are required.
- Use a root build context when shared packages or the root lockfile are needed;
  select the app-specific Dockerfile explicitly. Keep secrets out of the context.
- Keep dev and production credentials, databases, volumes, and migration targets
  separate. Do not reuse a production volume or database for development.
- Add a meaningful health check. Route only public HTTP services; never publish
  databases, queues, or admin ports to the host to make containers communicate.
- Configure corresponding resources in both environments unless the request
  explicitly limits scope. Preserve existing resource identities and storage.
- Set watch paths to include the app, shared packages, lockfiles, Dockerfiles,
  and Compose changes. Avoid filters that silently miss dependency updates.
- Store secrets through the correct environment/secret mechanism. If an API
  replaces an entire environment document, merge in protected memory and preserve
  all existing keys. Never put secrets in CLI arguments or public Vite variables.

For a new public hostname, configure the correct Dokploy service/port with
`https: false`, `certificateType: "none"`, and `domainType: "compose"`.
Check existing hostname ownership before creating the domain or DNS record.
Then follow the Caddy hostname procedure below; DNS plus a Dokploy route alone
does **not** make an unlisted hostname work through this edge proxy.

## 7. DNS, TLS, and shared proxy topology

```text
Visitor HTTPS
  -> Cloudflare proxied DNS/CDN
  -> Caddy HTTPS on host :443 (Let's Encrypt certificate)
  -> dokploy-traefik:80 on dokploy-network
  -> selected app service's internal HTTP port
```

Cloudflare-to-Caddy traffic is encrypted, unlike the HTTP-only origin described
by the generic skill for the older `flydexo.com` installation. Leave zone SSL
and existing hostname overrides intact; never switch to Flexible to mask a
routing problem. Dokploy domains remain HTTP internally because Caddy owns TLS.

- Edge Compose: `/etc/abelink-edge/docker-compose.yml`.
- Edge host allowlist: `/etc/abelink-edge/Caddyfile`.
- Edge environment: `/etc/abelink-edge/.env`, private; supplies ACME email.
- Certificate state: persistent `caddy_data` and `caddy_config` Compose volumes.
- Traefik config: `/etc/dokploy/traefik/traefik.yml`.
- Traefik dynamic routes: `/etc/dokploy/traefik/dynamic/`.
- Traefik trusts forwarded headers from Docker subnet `10.0.1.0/24`.
- Caddy publishes 80/443; Traefik publishes **no host ports**. Dokploy port 3000
  is bound on the host but blocked from the public Internet by the Hetzner firewall.

Treat Caddy, Traefik, the firewall, and Dokploy as shared infrastructure affecting
both environments. Do not restart them for an ordinary frontend deployment.
Preserve forwarded protocol information; authenticated apps must issue Secure
cookies over public HTTPS. Do not disable Secure cookies to repair login.

### Authorized new-hostname change

1. Confirm hostname ownership, target environment/service, and maintenance scope.
2. Back up the edge configuration securely; preserve all existing hostnames.
3. Add the hostname to the Caddyfile and validate before applying:

   ```bash
   ssh root@91.99.156.3 \
     'docker exec abelink-edge caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile'
   ```

4. Use the authorized Cloudflare connection to create/update only the relevant
   proxied A record to the verified server IP. Preserve mail, TXT, and unrelated
   DNS records. Configure the matching Dokploy domain and redeploy its Compose
   resource when labels change.
5. Caddy's admin API is disabled in this baseline, so do not assume `caddy reload`
   works. Applying an edited Caddyfile requires a planned recreation of `edge`:

   ```bash
   ssh root@91.99.156.3 \
     'cd /etc/abelink-edge && docker compose up -d --force-recreate edge'
   ```

   This briefly interrupts all three public hostnames. Obtain maintenance
   authorization first. Never delete certificate volumes. Check certificate
   issuance and every existing hostname after the change.

Do not hand-edit Dokploy-generated dynamic route files for normal app changes;
use its domain API/UI so configuration and running labels stay consistent.

## 8. Acceptance checks

All three layers must pass for the intended revision:

1. **Deployment:** the tracked deployment reports `done`, not just queued/running;
   its source revision and environment match the requested release.
2. **Runtime:** the intended containers are running and healthy. A healthy old
   container does not prove that a newer build deployed. Health may take at least
   one 30-second interval to settle before Traefik serves a new container.
3. **Public behavior:** verify HTTPS, correct app identity, referenced JS/CSS,
   and relevant app behavior. Compare deployed assets/source with the intended
   release when needed, rather than trusting a build's exit code alone.

Bound public checks so a redirect loop cannot hang an agent:

```bash
curl --fail --silent --show-error --location --max-redirs 5 --max-time 30 \
  --output /dev/null --write-out '%{http_code}\n' https://abelink.app/
curl --fail --silent --show-error --location --max-redirs 5 --max-time 30 \
  --output /dev/null --write-out '%{http_code}\n' https://dev.abelink.app/
curl --fail --silent --show-error --location --max-redirs 5 --max-time 30 \
  --output /dev/null --write-out '%{http_code}\n' https://dokploy.abelink.app/
```

An HTTP 200 alone can be a fallback/error page: check content identity and
assets too. For authenticated apps, use disposable sessions and close them.
The current demo form uses an external submission service; do not send real
emails or create external records just to smoke-test a deployment. Explicitly
state if interactive flows were not exercised. No browser work is implied by
this runbook; follow the current agent platform's browser-use instructions.

## 9. Troubleshooting and recovery

Start read-only. Read finite deployment/runtime log tails and redact before
sharing. A 404 immediately after deployment can be temporary health gating.

| Symptom | Investigate first | Avoid |
| --- | --- | --- |
| Build failure | Intended deployment log, commit, lockfile, context, build-time inputs | Repeated unchanged retries or deleting caches/volumes blindly |
| Deploy done, app unhealthy | Actual container health/logs, bind address, internal port, startup inputs | Assuming `done` proves app health |
| Public 404 | Hostname, domain service/port, container health, Caddy allowlist, live labels | Recreating the project or editing global TLS |
| Public 502/503 | Caddy -> Traefik -> app reachability and shared network | Publishing database/admin ports |
| TLS error / redirect loop | Certificate state, hostname-specific CF settings, scheme forwarding, Caddy vs. Dokploy TLS ownership | Enabling Dokploy TLS or weakening zone SSL |
| Missed auto-deploy | Remote branch, watch paths, hook delivery status, `autoDeploy`, build queue | Changing the shared GitHub App's global webhook |
| Login failure | Actual account, forwarded HTTPS, Secure cookie, auth settings | Disabling cookie security or exposing port 3000 |
| Disk/memory pressure | `df -h`, `free -h`, `docker system df`, bounded logs, build concurrency | Volume pruning or simultaneous builds to force progress |

Read-only host inspection:

```bash
ssh root@91.99.156.3 'docker service ls; docker ps; df -h /; free -h'
ssh root@91.99.156.3 'docker logs --tail 100 abelink-edge'
ssh root@91.99.156.3 'docker logs --tail 100 dokploy-traefik'
```

Local recovery access to Dokploy, if the public proxy is unavailable:

```bash
ssh -N -L 127.0.0.1:13000:127.0.0.1:3000 root@91.99.156.3
```

Access `http://127.0.0.1:13000` locally; keep the tunnel private and close it
afterward. Do not open port 3000 in the firewall. HTTPS-bound authentication
can behave differently over this recovery URL; do not weaken public auth to
make recovery easier. If an SSH host key changes unexpectedly, verify the
server's identity through trusted infrastructure access before updating it.

### Rollback

Identify the exact last-known-good revision/image and associated configuration.
Check database/migration compatibility even if the current landing page has no
database. A code rollback does not reverse data migrations or secret changes.
Use a rollback operation only if its behavior is verified in the installed
version. Otherwise propose an approved Git revert or explicit known-good image
deployment. Do not invent an API, force-push history, or call a branch redeploy
a rollback. Verify the recovered deployment using section 8.

## 10. Backups and upgrades

This is a single-server deployment, not a high-availability setup. Automatic
backups and a tested restore process are **not established by this runbook**.
Inspect existing backup jobs before claiming recoverability.

Before stateful or infrastructure work, inventory and securely back up:

- Dokploy PostgreSQL, containing deployment settings and GitHub credentials.
- Docker Swarm secrets, especially database and authentication secrets, using
  an appropriate separately secured recovery procedure; a database dump does
  not recreate Swarm secrets or all server state.
- `/etc/dokploy`, `/etc/abelink-edge`, Caddy certificate/config volumes, and any
  future application databases or volumes. Protect permissions and private keys.
- Source revisions, image versions/digests, network/firewall/proxy topology, and
  the intended recovery order. Keep encrypted copies off the server and test
  restoration on an isolated target before depending on them.

Do not commit backups or secret exports. A VM snapshot alone is not proof of
database consistency or successful restoration. Restores can overwrite current
state and require explicit approval and a recovery plan.

For upgrades: inspect current versions and installed API behavior, choose an
explicit target, review its authoritative release/migration guidance, back up,
and agree on a maintenance window and rollback path. Never run the installer
again as a repair or blindly upgrade Docker, Dokploy, Traefik, and Caddy together.
There is only 4 GB RAM and one configured build worker; avoid unnecessary build
concurrency. Pin tested image versions/digests as part of an authorized upgrade
rather than assuming a moving tag is reproducible.

**Critical:** Dokploy's standard Traefik recreation/update workflow may try to
publish ports 80/443. Preserve Caddy's ownership and the custom unexposed
Traefik topology, mounts, shared network, and trusted headers. If an upgrade
cannot preserve them, stop and plan the migration instead of creating a port
conflict. Re-discover the API and verify both apps, dashboard login, TLS, hooks,
and credential access after any shared-infrastructure upgrade.

## 11. Handoff and documentation upkeep

Summarize project/environment/service, source revision, observed deployment ID
and status, container health, public checks, changes made, and remaining risks.
Name failed or skipped checks; do not report queued work as deployed.

After authorized infrastructure changes, update this inventory and `AGENTS.md`
when their invariants change. Keep credentials and token-bearing URLs out of
both documents. Do not create commits or publish documentation without a request.

## 12. Backend dev auto-deployment (configured, not deployed)

On November 21, 2026, after the member requested deployment on their next dev
push, the existing `web` Compose in `abelink` / `dev` was configured through the
installed v0.31.4 API, without submitting a deployment:

- Compose ID: `XXp-RthZqER8mcRUd5_HS` (rediscover before another write).
- Repository/branch remain `Flydexo/abelink`, `dev`.
- Compose path: `./docker-compose.dev.yml`, extending the root frontend service
  and the backend service in `docker-compose.backend.dev.yml`.
- `autoDeploy=true`, trigger `push`, existing watch paths `["**"]` preserved.
- `createEnvFile=true`, so the dev Compose environment is available to Compose.
- The existing `/` domain remains attached to `web:80`.
- Backend domains were saved on `dev.abelink.app` for `/api`, `/health`, `/mcp`,
  and `/openapi.json`, attached to `backend:8000`, with `https=false`,
  `certificateType=none`, `stripPath=false`. These reach containers only after
  deployment applies their routing labels.
- Separate random `AUTH_SECRET` and `LINKCS_IMPORT_TOKEN` were generated
  privately and saved in dev only. `GOOGLE_CLOUD_LOCATION=global` and
  `PREFER_FREE_SEARCH=true` were saved. Never reproduce secret values here.
- The member still must provide `GOOGLE_CLOUD_PROJECT`,
  `GEMMA_MODEL`, `EMBEDDING_MODEL`, and `GOOGLE_APPLICATION_CREDENTIALS_JSON`.
  Merge them into this exact dev Compose's `env` before the next dev push;
  do not overwrite the generated secrets or unrelated variables.

No new Compose resource, database, persistent volume, DNS record, or shared
proxy configuration was created. Production retains its original source path,
branch, trigger and domain; it was not modified. No Git commit, push, image
build, container start, or deployment was submitted by the configuration work.
The member's next push can trigger a deployment; it will fail if source files
or required private inputs are missing. Configuration is not proof of runtime
health or a working authenticated application.

### Compose-managed dev database

The member subsequently requested that Compose deploy the database too. The
dev manifests now include `database` (PostgreSQL 16 with pgvector) and the
project-scoped named volume `postgres_data`. No database port is published.
The backend waits for database health, builds its internal `DATABASE_URL`
from `POSTGRES_PASSWORD`, and applies the existing migrations. An external
database URL is no longer a required input. The earlier no-database statement
above describes the initial configuration work, not this prepared stack.

Generate the dev database password privately as 32 random bytes encoded as hex
only if it is missing, and save it in the existing dev Compose's environment.
On November 21, 2026, `POSTGRES_PASSWORD` was generated privately and saved in
that dev Compose, preserving all other keys. Readback confirmed the stable
Compose project identity, `isolatedDeployment=false`, and
`isolatedDeploymentsVolume=false`; production configuration was unchanged.
Never rotate it implicitly: PostgreSQL initializes its SQL password only on an
empty volume. Preserve the Compose project identity and the data volume; do not
use `down -v`. Backup, restore, password rotation and major-version upgrades
require separate authorized procedures. No database container or volume is
created until an actual deployment; production remains unchanged.

The dev backend requires a dedicated PostgreSQL with pgvector and pgcrypto,
fixes embeddings at 768, and disables demo authentication. It exposes no host
ports. `/app/import-linkcs` provides a protected JSON upload to seed the
database with the dedicated `LINKCS_IMPORT_TOKEN`; this does not create a
student login or bypass authorization requirements.

See `backend/deploy/README.md` for secret handling, validation and the remaining
authentication/data/ranking blockers. `backend/deploy/dev.env.example` is a
public key-name template only, never the storage location for real credentials.

### Environment-backed secret startup failure

The member's subsequent dev deployment log shows both images built and
PostgreSQL healthy, but backend startup failed with `cannot create secret`
in a `read-only service` because `file` is the sole supported option there.
This is not evidence of invalid Google credentials or a database failure.

The dev backend manifest now explicitly sets `read_only: false` so Compose can
copy the environment-backed Google secret into the container before startup.
The non-root user, dropped capabilities, no-new-privileges and temporary-file
limits remain. No secret source, database volume, password, production service,
or Dokploy setting needs changing for this fix. A configuration-only check
does not test secret injection; the corrected source must be published and the
next intended deployment checked before claiming a successful backend start.

### Reserved identifier in the initial migration

The member's November 21, 2026 startup log subsequently showed a PostgreSQL
syntax error on `current_role` in `001_init.sql`. This is a reserved SQL value,
so the column identifier must be double-quoted both in its declaration and in
the generated search-vector expression. Raw search SQL now quotes it too;
SQLAlchemy's PostgreSQL dialect already quotes the ORM attribute correctly.
The column name stays the same: no schema rename, data reset, password change
or volume removal is required. The existing transactional startup migration
runner will retry the corrected idempotent SQL on the next deployment.

`backend/tests/test_sql_migrations.py` checks migration syntax using PostgreSQL's
parser through the dev-only `pglast` dependency, verifies that the search vector
reads the profile column rather than the database session role, and checks ORM
quoting. These checks do not connect to or migrate the deployed database.

### Explicitly requested public dev access

The member subsequently requested that everyone can chat, upload LinkCS JSON
and use MCP without authentication. The dev manifest now fixes
`ALLOW_PUBLIC_ACCESS=true`, while keeping `DEMO_MODE=false` and
`ALLOW_DEMO_AUTH=false`. The backend default remains protected
(`allow_public_access=False`) outside this manifest; production is unchanged.

Startup creates one shared `Visiteur public` profile if missing, without real
personal details, mock alumni or provider calls. It supports chat on an empty
database. `X-Profile-Id` on REST and `user_email_or_id` on MCP select context,
not a verified identity. There is no per-visitor data isolation. Anonymous
requests can inspect profiles, import shared data and spend provider credits.
The member was warned of these consequences; no anonymous quota was added.

Public LinkCS imports omit `X-LinkCS-Import-Token` but keep confirmation, JSON
validation, size/relationship limits and additive transactions. Preserve any
existing import key in Dokploy; it is unused publicly and still protects imports
when public mode is disabled. Token management routes are omitted publicly.
The frontend hides the key/token forms and provides a token-free MCP config.
`/health` reports `public_access` for frontend behavior and verification.

These are source changes, not a live setting change or deployment. A dev push
must publish them before the public mode takes effect. Do not rotate secrets,
delete database data, push or deploy merely to validate this change.
