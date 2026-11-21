# Abelink analytics and tagging plan

## Setup

The website uses Abelink's PostHog project key and the managed reverse proxy
`https://t.abelink.app`. The public project key can be overridden with this
**build-time** variable wherever the Docker image is built:

| Variable | Value |
| --- | --- |
| `VITE_POSTHOG_KEY` | The project's public project API key |

The key is intentionally public and must never be an ingest personal API key.
The Docker build passes overrides to Vite; setting them only as container
runtime variables will not configure the static website. For a local build, put
the key override in an ignored `.env.local` file at the repository root. The
ingest host is fixed to `https://t.abelink.app` in the analytics module.

PostHog initializes on page load without an analytics consent prompt. PostHog
autocapture, page-leave capture, session recording, and person profiles are
disabled. The website sends a manual `$pageview` on page load. Query strings and
URL fragments are removed from captured `$current_url` values. The SDK uses
PostHog defaults `2026-05-30`.

## Events

Event names use lower snake case and describe completed actions. Keep properties
small, stable, and free of user-entered content.

| Event | When | Properties |
| --- | --- | --- |
| `$pageview` | Once on page load | PostHog's standard page context |
| `demo_request_opened` | A demo request dialog opens | `placement`: `navigation`, `hero`, `audiences`, or `footer_cta` |
| `demo_request_submitted` | FormSubmit confirms the request | None |
| `demo_request_failed` | FormSubmit request fails | None |
| `interactive_demo_search_submitted` | Search starts in the interactive demo | `source`: `manual_search`, `suggestion`, `autoplay`, or `replay` |
| `interactive_demo_result_viewed` | An interactive demo result appears | Same `source` values |
| `interactive_demo_replayed` | Visitor clicks “Voir en action” | None |
| `faq_item_opened` | A FAQ answer is opened | `question_index`: one-based position in the FAQ |

## Privacy rules

- Never send names, email addresses, alumni network names, free-text searches,
  search content, form payloads, or clipboard content to analytics.
- Keep autocapture and session recording disabled.
- Use the dashboard to compare the funnel from pageview to dialog open to
  successful request. Segment CTA opens by `placement`; compare demo search
  completion by `source`.
- Keep event names and property meanings stable. Add a row here whenever an
  event is introduced or changed, and remove obsolete events from dashboards.
