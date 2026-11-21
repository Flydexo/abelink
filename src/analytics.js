const CONSENT_KEY = 'abelink_analytics_consent'
const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY || 'phc_ycuFUh9BCfEhDC3bRqLzyhg744pc82Hw5T77XgB5LeWB'
const POSTHOG_HOST = import.meta.env.VITE_POSTHOG_HOST || 'https://t.abelink.app'
let client
let initializing

export const hasAnalyticsConfig = Boolean(POSTHOG_KEY)

export function getAnalyticsConsent() {
  try {
    const value = localStorage.getItem(CONSENT_KEY)
    return value === 'accepted' || value === 'rejected' ? value : null
  } catch {
    return null
  }
}

export async function setAnalyticsConsent(value) {
  try {
    localStorage.setItem(CONSENT_KEY, value)
  } catch {}
  if (value === 'accepted') {
    if (client) {
      client.opt_in_capturing()
      client.capture('$pageview')
    } else initializeAnalytics()
  }
  if (value === 'rejected' && client) client.opt_out_capturing()
}

export function initializeAnalytics() {
  if (!hasAnalyticsConfig || getAnalyticsConsent() !== 'accepted') return
  initializing ||= import('posthog-js').then(({ default: posthog }) => {
    if (getAnalyticsConsent() !== 'accepted') return
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
  if (getAnalyticsConsent() !== 'accepted') return
  if (client) client.capture(event, properties)
  else initializeAnalytics()?.then(() => {
    if (getAnalyticsConsent() === 'accepted') client?.capture(event, properties)
  })
}
