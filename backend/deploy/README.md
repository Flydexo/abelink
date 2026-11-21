# Backend dev deployment preparation

The complete dev stack uses `docker-compose.dev.yml`, extending the existing
frontend definition and `docker-compose.backend.dev.yml`. Production still
uses the frontend-only `docker-compose.yml`. A configured auto-deploy does not
mean the backend has already been deployed or that missing credentials exist.
Do not push the branch or deploy manually without the corresponding user
request. Follow `docs/DEPLOYMENT.md` for instance credentials and discovery.

## Target and isolation

- Dokploy: `https://dokploy.abelink.app`, project `abelink`, environment `dev`.
- Resource: the existing Compose named `web` in `dev`, GitHub repository
  `Flydexo/abelink`, branch `dev`, Compose path `./docker-compose.dev.yml`.
- Its `web`, `backend`, and `database` services deploy together on a push to `dev`. Reuse
  this resource; do not create an additional backend stack or duplicate hook.
- Build context: `./backend`, internal service `backend`, port `8000`.
- Compose provides a dedicated PostgreSQL 16 + pgvector `database` service and
  project-scoped `postgres_data` volume. No host ports, DNS records, or shared
  proxy changes are included. The root frontend definition is unchanged.
- Preserve the existing GitHub integration, push trigger, and `**` watch paths.
  The dev Compose path changes; production's source configuration does not.
- Local preparation files do not reach a GitHub-source build until an explicitly
  authorized commit and push publishes them.

## Private inputs

`dev.env.example` lists the inputs; it contains no credentials. Supply actual
values through private secret entry or Dokploy environment settings, never chat,
Git, a frontend `VITE_*` variable, or a Docker build argument.

| Variable | Required | Meaning |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | Yes | Generate privately as 32 random bytes encoded as hex if absent; preserve it after the database volume is initialized. Compose builds the backend connection URL automatically. |
| `GOOGLE_CLOUD_PROJECT` | Yes | Google Cloud project identifier. |
| `GOOGLE_CLOUD_LOCATION` | Defaults to `global` | Location compatible with the selected models. |
| `GEMMA_MODEL` | Yes | Generation model verified as available to this project. |
| `EMBEDDING_MODEL` | Yes | Embedding model verified as available with 768 output dimensions. |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Yes for this Compose | Complete Google credential JSON, delivered as a Compose secret, not a container environment variable. |
| `AUTH_SECRET` | Yes | Strong, random JWT secret dedicated to dev; it can be generated privately before configuration. |
| `LINKCS_IMPORT_TOKEN` | For Abelink bundle imports or protected LinkCS imports | Preserve the existing value. Public LinkCS list imports do not use this key. |
| `TAVILY_API_KEY` | Optional | Tavily fallback credentials. |
| `PREFER_FREE_SEARCH` | Defaults to `true` | DuckDuckGo first, Tavily fallback; `false` selects Tavily directly when its key exists. |
| `LINKEDIN_LI_AT` | Optional, leave empty initially | Sensitive LinkedIn session cookie, used only by the photo-fetch fallback in the current code. |

The Compose deliberately fixes `DEMO_MODE=false`, `ALLOW_DEMO_AUTH=false`,
`ALLOW_PUBLIC_ACCESS=true`, `EMBEDDING_DIM=768`, `CORS_ORIGINS=https://dev.abelink.app`, and
`PUBLIC_API_URL=https://dev.abelink.app`. It disables the memory-mode SQLite
cache. Missing database, project, model, or JWT settings refuse Compose
interpolation rather than silently selecting demo defaults.

### Agent procedure: save values in Dokploy

1. Obtain missing values through the platform's private secret-entry mechanism.
   Do not ask for credentials in chat and do not fill the tracked example file.
2. Rediscover the `abelink` project, `dev` environment, and existing `web` Compose;
   verify its branch, manifest path, and installed `compose.update` schema.
3. Read that resource's `env` privately. Merge the supplied keys with existing
   values, preserving every unrelated key. If `AUTH_SECRET` or
   `LINKCS_IMPORT_TOKEN` is absent, generate a separate cryptographically random
   dev secret for each privately; never silently rotate existing secrets.
4. When configuration is authorized, save the merged document to that exact
   Compose's `env` field in Dokploy. Local shell exports or local `.env` files
   alone do not set the environment of a later GitHub-triggered deployment.
5. Read it back in private and verify required key presence and correct secret
   wiring. Report names and missing keys only. Do not print the dotenv document,
   expanded Compose with real values, or full configuration API responses.
6. If values or permissions are missing, report the blocker rather than saying
   the environment is configured. No placeholder credentials in a real deploy.
7. Source publication and deployment remain separate authorizations. Once the
   real values are saved, the member's push to `dev` triggers the complete
   stack automatically; do not also submit a manual deployment for that push.

### Compose-managed PostgreSQL

The `database` service uses `pgvector/pgvector:0.8.7-pg16-trixie`, database
`abelink_dev`, and user `abelink`. Only the Compose network can reach it; do not
publish port 5432 or add a public domain. The backend receives its internal
`DATABASE_URL` from Compose, waits for the database health check, and applies
the existing idempotent migrations, including the vector extension.

The project-scoped named volume `postgres_data` preserves data across rebuilds
and pushes. Keep the Dokploy Compose project identity stable. No external
PostgreSQL service or `DATABASE_URL` input is needed. A legacy `DATABASE_URL`
in Dokploy is ignored by this manifest; do not delete unrelated environment keys.

Generate `POSTGRES_PASSWORD` privately only if absent and save it in the existing
dev Compose's `env`. Use hex to keep the interpolated connection URL valid.
Postgres applies this value only to an empty data directory: changing the env
does not change an existing SQL password. Never run `down -v`, delete the volume,
or change the PostgreSQL major version to fix a deployment. Back up before any
authorized storage maintenance; backups and restores are not implemented by
this Compose. Production and Dokploy's administration database remain separate.

### Google credentials

The Compose secret reads `GOOGLE_APPLICATION_CREDENTIALS_JSON` from the Compose
process environment and injects a file at `/run/secrets/google-adc.json` before
the container starts (default file mode 0444).
The container receives only `GOOGLE_APPLICATION_CREDENTIALS` pointing to this
file. The JSON is not copied into the image. Use a dedicated, least-privilege
dev identity; do not provide a personal browser cookie as Google credentials.

When encoding JSON in a dotenv document, use compact JSON as a single quoted
value and retain JSON escapes such as `\n` inside the private key. Do not print
the expanded Compose configuration with real credentials. Confirm that the
installed Docker Compose supports environment-backed secrets and that Dokploy
provides this input to its Compose process before deploying. If not, stop and
prepare an approved protected file mount; never bake the JSON into the image.

Keep `backend.read_only: false`. Docker Compose copies environment-backed
secrets into the container filesystem, and refuses to do so with a read-only
root filesystem (`file` is the sole supported secret source in that case).
The application still runs as the image's non-root user with all capabilities
dropped and `no-new-privileges`. The credentials remain out of the image,
frontend assets and application environment. `docker compose config` alone
does not exercise this secret injection or prove runtime compatibility.

## Proposed public routing

Reuse the existing `dev.abelink.app` hostname, avoiding DNS or Caddy changes.
The dev Compose needs these path-specific Dokploy domains for its backend:

| Host | Path | Service | Port |
| --- | --- | --- | --- |
| `dev.abelink.app` | `/api` | `backend` | 8000 |
| `dev.abelink.app` | `/health` | `backend` | 8000 |
| `dev.abelink.app` | `/mcp` | `backend` | 8000 |
| `dev.abelink.app` | `/openapi.json` | `backend` | 8000 |

Use `https=false`, `certificateType=none`, and `stripPath=false`. Public URLs
remain HTTPS. Preserve the existing frontend route `/` and production routes.
Verify the generated routing rules and precedence before applying: this table
is a proposal, not proof that routes exist. Add `/docs` or `/redoc` only if API
documentation is intentionally made public. Frontend calls can use their
existing same-origin URLs, without a new `VITE_API_URL` build.

## Preconditions and known blockers

1. The dev database must support `vector` and `pgcrypto`. Startup runs the SQL
   migrations and writes its schema. Confirm the target database and privileges
   first; this preparation does not authorize creating infrastructure.
2. A new database starts empty. A reviewed, authorized dataset and user profile
   must exist before search can work; do not seed personal or mock data by
   default. `LINKCS_DATA_PATH` is a memory-mode feature, not PostgreSQL seeding.
3. At the member's explicit request, dev fixes `ALLOW_PUBLIC_ACCESS=true` while
   keeping demo mode/auth off. REST and MCP need no token. Startup creates a
   shared visitor context even on an empty database; selecting another profile
   is not authentication. Do not advertise per-user privacy or verified identity.
4. Anyone with the URL can read profiles, import data and trigger paid provider
   calls. There is no anonymous quota or visitor isolation. Use only data
   intended for this shared environment and monitor provider usage. The default
   outside this dev manifest stays `ALLOW_PUBLIC_ACCESS=false`.
5. PostgreSQL does not persist `embedding_space`, although the ranking code uses
   it. Correct and test this before relying on Vertex ranking after reload.
6. Python dependency versions use lower bounds, not a lockfile. Record the tested
   image and installed versions before treating a build as reproducible.
7. Use one backend worker initially: the NetworkX graph is process-local and has
   no cross-worker invalidation.

## Validation and eventual deployment

Before supplying secrets, validate the manifest using disposable dummy inputs:

```bash
POSTGRES_PASSWORD=validation0123456789 \
GOOGLE_CLOUD_PROJECT=validation \
GEMMA_MODEL=validation \
EMBEDDING_MODEL=validation \
AUTH_SECRET=validation-only-not-for-deployment \
LINKCS_IMPORT_TOKEN=validation-only-not-for-deployment \
GOOGLE_APPLICATION_CREDENTIALS_JSON="{}" \
docker compose -f docker-compose.dev.yml config --quiet
```

This validates configuration only. It makes no database or Google calls and
must never be used to start a deployment. Build and run the backend tests where
Docker/Python are available; do not claim they passed from configuration alone.

Once the member publishes the prepared source with a push to `dev`, the existing
GitHub auto-deploy builds the intended revision using the dev manifest. Before
that push, supply all required private inputs and resolve public-exposure
blockers. Do not manually deploy the same push again. Verify, in order:

1. The intended deployment finishes successfully and the backend is healthy.
2. `https://dev.abelink.app/health` returns JSON, `status=ok`,
   `database.backend=postgres`, and `demo_mode=false`.
3. `llm_backend=vertex` is necessary but not sufficient: verify an authorized,
   bounded real model/embedding call, since the application can fall back.
4. Public REST chat and MCP tool calls work without Authorization, LinkCS upload
   works without an import key, and invalid/unconfirmed dumps remain rejected.
   Protected deployments must still reject unauthenticated requests with 401.
5. A reviewed small search returns grounded profiles and paths, and a streaming
   response reaches the client without being buffered into a static page.
6. The dev frontend HTML/assets still work and production remains unaffected.

The Compose health check requires an actual PostgreSQL backend rather than
accepting a successful HTTP response from an in-memory demo. It does not prove
Google/Tavily connectivity, dataset quality, correct permissions, or user login.

## LinkCS upload and initial data

The page `/app/import-linkcs` accepts LinkCS JSON lists from any visitor in public dev,
without a key or account, including on an empty database. The member explicitly
authorized this shared access. Outside public mode, the dedicated
`LINKCS_IMPORT_TOKEN` is still required; do not expose its stored value.

The upload endpoint requires explicit confirmation, and only in protected mode
the header `X-LinkCS-Import-Token`. It is limited to 10 MiB, 5,000 objects and 100,000
generated relations. Existing profiles and relations are preserved; stable
LinkCS IDs and normalized LinkedIn URLs identify existing profiles. PostgreSQL
inserts new profiles and relations in a single transaction. The graph reloads
after commit. No paid embeddings/enrichment or external search is performed.
The raw dump is not retained or sent to analytics. Memory-mode imports are
temporary and the page reports this explicitly.

The same page accepts the v1 JSON database bundle produced by
`scripts.export_import_bundle export` (up to 1 GiB, PostgreSQL only). A bundle
requires the existing `LINKCS_IMPORT_TOKEN` even in public dev. Each request
transfers up to 4 MiB; the upload is temporarily stored on the backend's writable
container filesystem (`BUNDLE_UPLOAD_DIRECTORY=/app` in dev), not the 64 MiB
`/tmp` tmpfs. Allow disk space for the bundle and database growth. Use a single
backend worker/replica: upload state is held in one process, uploads expire
after 15 minutes idle and do not survive a restart. Only one bundle can be
uploaded or processed at a time. The graph refreshes after the additive
transaction commits; no inference or AI calls are run by the bundle import.

In public mode, `/mcp` and `/mcp/` accept tool calls without a Bearer token.
Use `user_email_or_id` to select a profile context, or omit it for the shared
visitor. The frontend integrations tab provides token-free configuration and
the public API omits personal-token management routes. Outside public mode,
Bearer authentication and the separate import key remain unchanged.
