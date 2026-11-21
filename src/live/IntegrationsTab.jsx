import { useEffect, useState } from 'react'
import { createApiToken, listApiTokens, revokeApiToken } from '../api.js'

export default function IntegrationsTab({ activeUser }) {
  const [tokens, setTokens] = useState([])
  const [label, setLabel] = useState('Claude MCP / ChatGPT')
  const [createdToken, setCreatedToken] = useState(null)
  const [copiedKey, setCopiedKey] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8000'
  const mcpUrl = `${origin}/mcp`
  const openApiUrl = `${origin}/openapi.json`

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      const items = await listApiTokens(activeUser?.id)
      setTokens(items)
    } catch (err) {
      setError(err.message || 'Impossible de lister les tokens.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [activeUser?.id])

  async function handleCreate(e) {
    e.preventDefault()
    setError('')
    try {
      const created = await createApiToken(label.trim() || 'Token personnel', activeUser?.id)
      setCreatedToken(created)
      await refresh()
    } catch (err) {
      setError(err.message || 'Impossible de créer le token.')
    }
  }

  async function handleRevoke(tokenId) {
    setError('')
    try {
      await revokeApiToken(tokenId, activeUser?.id)
      setTokens((prev) => prev.filter((t) => t.id !== tokenId))
    } catch (err) {
      setError(err.message || 'Impossible de révoquer le token.')
    }
  }

  async function copyText(key, value) {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedKey(key)
      setTimeout(() => setCopiedKey(''), 1800)
    } catch {}
  }

  const claudeSnippet = JSON.stringify(
    {
      mcpServers: {
        abelink: {
          type: 'http',
          url: mcpUrl,
          headers: {
            Authorization: `Bearer ${createdToken?.token || 'abk_votre_token'}`,
          },
        },
      },
    },
    null,
    2,
  )

  return (
    <div className="app-panel">
      <div className="app-panel-head">
        <h2>Connecter Claude (MCP) &amp; ChatGPT (Actions)</h2>
        <p className="muted">
          Générez un jeton Bearer personnel lié à <strong>{activeUser?.full_name || 'l’étudiant actif'}</strong> pour interroger Abelink directement depuis Claude ou un GPT personnalisé.
        </p>
      </div>

      <form className="app-token-form" onSubmit={handleCreate}>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Nom du token (ex. Claude Desktop)"
          aria-label="Nom du token"
        />
        <button type="submit" className="btn primary">Générer un token Bearer</button>
      </form>

      {error && <p className="form-error" role="alert">{error}</p>}

      {createdToken && (
        <div className="app-token-reveal">
          <div>
            <strong>Token créé ({createdToken.label}) — copiez-le maintenant</strong>
            <code className="app-code-inline">{createdToken.token}</code>
          </div>
          <button
            type="button"
            className="btn ghost app-btn-sm"
            onClick={() => copyText('new_token', createdToken.token)}
          >
            {copiedKey === 'new_token' ? 'Copié' : 'Copier le token'}
          </button>
        </div>
      )}

      <div className="app-integrations-grid">
        <section className="app-subbox">
          <h3>Claude — Serveur MCP (Streamable HTTP)</h3>
          <p className="muted small">
            Endpoint : <code>{mcpUrl}</code> · Expose <code>search_alumni_action_plan</code>, <code>get_more_connections</code> et <code>draft_outreach_message</code>.
          </p>
          <pre className="app-pre">{claudeSnippet}</pre>
          <button
            type="button"
            className="btn ghost app-btn-sm"
            onClick={() => copyText('claude_json', claudeSnippet)}
          >
            {copiedKey === 'claude_json' ? 'Configuration copiée' : 'Copier la config MCP'}
          </button>
        </section>

        <section className="app-subbox">
          <h3>ChatGPT — GPT Actions (OpenAPI 3.1)</h3>
          <p className="muted small">
            Importez le schéma OpenAPI dans ChatGPT et choisissez l’authentification <strong>Bearer</strong> avec votre jeton personnel.
          </p>
          <div className="app-endpoint-box">
            <code>{openApiUrl}</code>
            <button
              type="button"
              className="btn ghost app-btn-sm"
              onClick={() => copyText('openapi', openApiUrl)}
            >
              {copiedKey === 'openapi' ? 'URL copiée' : 'Copier l’URL OpenAPI'}
            </button>
          </div>
          <p className="muted small">
            Opération principale : <code>recommend_alumni_action_plan</code> (<code>POST /api/v1/search/action-plan</code>) qui exécute tout le pipeline en une seule requête.
          </p>
        </section>
      </div>

      <section className="app-subbox">
        <div className="app-subbox-head">
          <h3>Tokens actifs</h3>
          {loading && <span className="muted small">Actualisation…</span>}
        </div>
        {tokens.length === 0 ? (
          <p className="muted small">Aucun token actif pour ce profil.</p>
        ) : (
          <ul className="app-token-list">
            {tokens.map((t) => (
              <li key={t.id}>
                <div>
                  <strong>{t.label}</strong>
                  <span className="muted small">
                    Créé le {new Date(t.created_at).toLocaleDateString('fr-FR')}
                    {t.last_used_at ? ` · Utilisé le ${new Date(t.last_used_at).toLocaleDateString('fr-FR')}` : ''}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn ghost app-btn-sm"
                  onClick={() => handleRevoke(t.id)}
                >
                  Révoquer
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
