const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY || 'phc_ycuFUh9BCfEhDC3bRqLzyhg744pc82Hw5T77XgB5LeWB'
const POSTHOG_HOST = 'https://t.abelink.app'
let client
let initializing

export function initializeAnalytics() {
  if (!POSTHOG_KEY || client || initializing) return initializing
  initializing ||= import('posthog-js').then(({ default: posthog }) => {
    client = posthog
    posthog.init(POSTHOG_KEY, {
      api_host: POSTHOG_HOST,
      defaults: '2026-05-30',
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      person_profiles: 'never',
      persistence: 'localStorage',
      before_send: (event) => {
        const currentUrl = event?.properties?.$current_url
        if (currentUrl) {
          try {
            const url = new URL(currentUrl)
            url.search = ''
            url.hash = ''
            event.properties.$current_url = url.toString()
          } catch {}
        }
        return event
      },
    })
    posthog.capture('$pageview')
  }).finally(() => { initializing = undefined })
  return initializing
}

export function track(event, properties = {}) {
  if (client) client.capture(event, properties)
  else initializeAnalytics()?.then(() => {
    client?.capture(event, properties)
  })
}
