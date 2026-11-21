import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchHealth, fetchMe, searchDirectory } from '../api.js'
import { track } from '../analytics.js'
import ChatView from './ChatView.jsx'
import IntegrationsTab from './IntegrationsTab.jsx'
import LinkedInTab from './LinkedInTab.jsx'
import LinkCSTab from './LinkCSTab.jsx'
import ProfileAvatar from './ProfileAvatar.jsx'
import ProfileDrawer from './ProfileDrawer.jsx'

export default function LiveApp({ onNavigateHome, onNavigate, pathname = '/app' }) {
  const [tab, setTab] = useState(pathname === '/app/import-linkcs' ? 'linkcs' : 'chat')
  const [health, setHealth] = useState(null)
  const [backendError, setBackendError] = useState('')

  const [activeUserId, setActiveUserId] = useState('')
  const [activeUser, setActiveUser] = useState(null)
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const [memberQuery, setMemberQuery] = useState('')
  const [memberResults, setMemberResults] = useState([])

  const [drawerProfileId, setDrawerProfileId] = useState(null)

  const switcherRef = useRef(null)

  useEffect(() => {
    setTab((current) => pathname === '/app/import-linkcs' ? 'linkcs' : current === 'linkcs' ? 'chat' : current)
  }, [pathname])

  function selectTab(nextTab) {
    setTab(nextTab)
    onNavigate?.(nextTab === 'linkcs' ? '/app/import-linkcs' : '/app')
  }

  const loadHealthAndMe = useCallback(async (userIdOverride = activeUserId) => {
    try {
      const h = await fetchHealth()
      setHealth(h)
      setBackendError('')
      const me = await fetchMe(userIdOverride || null)
      setActiveUser(me)
      if (!userIdOverride) setActiveUserId(me.id)
    } catch (err) {
      setBackendError(err.message || 'Backend injoignable.')
    }
  }, [activeUserId])

  useEffect(() => {
    track('live_app_opened')
    loadHealthAndMe('')
  }, [])

  useEffect(() => {
    if (!switcherOpen) return
    let cancelled = false
    const timer = setTimeout(() => {
      searchDirectory(memberQuery, 15, activeUserId)
        .then((items) => {
          if (!cancelled) setMemberResults(items)
        })
        .catch(() => {})
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [switcherOpen, memberQuery, activeUserId])

  useEffect(() => {
    if (!switcherOpen) return
    const onDocClick = (e) => {
      if (switcherRef.current && !switcherRef.current.contains(e.target)) {
        setSwitcherOpen(false)
      }
    }
    addEventListener('mousedown', onDocClick)
    return () => removeEventListener('mousedown', onDocClick)
  }, [switcherOpen])

  async function handleSelectMember(member) {
    setSwitcherOpen(false)
    setActiveUserId(member.id)
    try {
      const me = await fetchMe(member.id)
      setActiveUser(me)
    } catch {}
  }

  return (
    <div className="app-shell">
      <header className="nav">
        <div className="app-nav-in">
          <div className="app-nav-left">
            <a
              className="logo"
              href="/"
              onClick={(e) => {
                e.preventDefault()
                onNavigateHome?.()
              }}
              aria-label="Abelink, retour à la présentation"
            >
              Abe<span>link</span>
            </a>

            <div className={`app-status-pill${health?.status === 'ok' ? ' ok' : ' err'}`}>
              <span className="app-status-dot" aria-hidden="true" />
              {health?.status === 'ok'
                ? `${health.graph?.nodes || 0} profils · ${health.enriched_profiles || 0} enrichis · ${health.search_provider === 'free_first' ? 'Web gratuit + Gemma 4' : health.tavily_enabled ? 'Tavily + Gemma 4' : 'Mode démo'}`
                : 'Backend hors ligne'}
            </div>
          </div>

          <nav className="app-tabs" aria-label="Espace de travail">
            <button
              type="button"
              className={`app-tab${tab === 'chat' ? ' active' : ''}`}
              onClick={() => selectTab('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              className={`app-tab${tab === 'linkedin' ? ' active' : ''}`}
              onClick={() => selectTab('linkedin')}
            >
              Import LinkedIn
            </button>
            <button
              type="button"
              className={`app-tab${tab === 'linkcs' ? ' active' : ''}`}
              onClick={() => selectTab('linkcs')}
            >
              Import LinkCS
            </button>
            <button
              type="button"
              className={`app-tab${tab === 'integrations' ? ' active' : ''}`}
              onClick={() => selectTab('integrations')}
            >
              Claude &amp; ChatGPT
            </button>
          </nav>

          <div className="app-nav-right" ref={switcherRef}>
            <button
              type="button"
              className="app-user-btn"
              onClick={() => setSwitcherOpen((v) => !v)}
              aria-expanded={switcherOpen}
            >
              <span className="app-user-avatar">
                <ProfileAvatar
                  src={activeUser?.photo_url}
                  name={activeUser?.full_name || 'Léo Bernard'}
                  fallback={activeUser?.full_name ? undefined : 'LB'}
                />
              </span>
              <span className="app-user-name">{activeUser?.full_name || 'Léo Bernard'}</span>
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>

            {switcherOpen && (
              <div className="app-switcher-menu" role="dialog" aria-label="Changer de profil actif">
                <input
                  value={memberQuery}
                  onChange={(e) => setMemberQuery(e.target.value)}
                  placeholder="Rechercher un membre (nom, email, asso)…"
                  autoFocus
                />
                <ul className="app-switcher-list">
                  {memberResults.map((m) => (
                    <li key={m.id}>
                      <button
                        type="button"
                        className={m.id === activeUser?.id ? 'active' : ''}
                        onClick={() => handleSelectMember(m)}
                      >
                        <span className="app-switcher-avatar" aria-hidden="true">
                          <ProfileAvatar src={m.photo_url} name={m.full_name} />
                        </span>
                        <span className="app-switcher-text">
                          <strong>{m.full_name}</strong>
                          <span className="muted small">{m.short_meta || 'Réseau CentraleSupélec'}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                  {memberResults.length === 0 && (
                    <li className="muted small app-switcher-empty">Aucun membre trouvé.</li>
                  )}
                </ul>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className={`app-main${tab === 'chat' ? ' app-main-chat' : ''}`}>
        {backendError && (
          <div className="app-offline-banner" role="alert">
            <div>
              <strong>Connexion à l’espace de travail indisponible ({backendError})</strong>
              <p className="muted small">
                Vérifiez le backend et votre authentification. Pour une démo locale uniquement :
                <code className="app-code-block">
                  cd backend &amp;&amp; DEMO_MODE=true .venv/bin/uvicorn app.main:app --reload --port 8000
                </code>
              </p>
            </div>
            <button type="button" className="btn ghost app-btn-sm" onClick={() => loadHealthAndMe()}>
              Réessayer
            </button>
          </div>
        )}

        {tab === 'chat' && (
          <ChatView
            activeUser={activeUser}
            activeUserId={activeUserId}
            onSelectPerson={(id) => setDrawerProfileId(id)}
          />
        )}

        {tab === 'linkedin' && (
          <LinkedInTab
            activeUser={activeUser}
            onImported={() => loadHealthAndMe(activeUserId)}
          />
        )}

        {tab === 'integrations' && <IntegrationsTab activeUser={activeUser} />}
        {tab === 'linkcs' && <LinkCSTab onImported={() => loadHealthAndMe(activeUserId)} />}
      </main>

      <ProfileDrawer
        profileId={drawerProfileId}
        activeUserId={activeUserId}
        onClose={() => setDrawerProfileId(null)}
      />
    </div>
  )
}
