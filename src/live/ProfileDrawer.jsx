import { useEffect, useState } from 'react'
import { fetchProfile } from '../api.js'
import ProfileAvatar from './ProfileAvatar.jsx'

const SOURCE_LABELS = {
  BASE_DB: 'Base annuaire',
  LINKCS_DB: 'Base LinkCS',
  WEB_TAVILY: 'Enrichi Tavily + Gemma 4',
  LINKEDIN_ARCHIVE: 'Archive LinkedIn',
}

export default function ProfileDrawer({ profileId, activeUserId, onClose }) {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!profileId) return
    let cancelled = false
    setLoading(true)
    setError('')
    fetchProfile(profileId, activeUserId)
      .then((data) => {
        if (!cancelled) setProfile(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Impossible de charger la fiche.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [profileId, activeUserId])

  useEffect(() => {
    if (!profileId) return
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [profileId, onClose])

  if (!profileId) return null

  return (
    <div className="app-drawer-backdrop" onClick={onClose}>
      <aside
        className="app-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-profile-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="app-drawer-head">
          <div className="app-drawer-identity">
            {profile && (
              <span className="app-drawer-avatar" aria-hidden="true">
                <ProfileAvatar src={profile.photo_url} name={profile.full_name} />
              </span>
            )}
            <div>
              <h2 id="drawer-profile-title">{profile?.full_name || 'Fiche profil'}</h2>
              {profile && (
                <p className="muted small">
                  {[profile.current_role, profile.current_company, profile.promo_year ? `Promo ${profile.promo_year}` : null]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              )}
            </div>
          </div>
          <button type="button" className="app-icon-btn" onClick={onClose} aria-label="Fermer la fiche">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
              <path d="M4.5 4.5l9 9M13.5 4.5l-9 9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {loading && <p className="muted">Chargement de la fiche…</p>}
        {error && <p className="form-error" role="alert">{error}</p>}

        {profile && !loading && (
          <div className="app-drawer-body">
            <div className="app-badge-row">
              <span className="app-badge accent">
                {SOURCE_LABELS[profile.enrichment_source] || profile.enrichment_source}
              </span>
              {profile.sector && <span className="app-badge neutral">{profile.sector}</span>}
              {profile.location && <span className="app-badge neutral">{profile.location}</span>}
            </div>

            {profile.bio && (
              <section className="app-drawer-sec">
                <h3>Parcours</h3>
                <p>{profile.bio}</p>
              </section>
            )}

            {profile.experiences?.length > 0 && (
              <section className="app-drawer-sec">
                <h3>Expériences</h3>
                <ul className="app-plain-list">
                  {profile.experiences.map((exp, idx) => (
                    <li key={`${exp.company}-${idx}`}>
                      <strong>{exp.role || 'Poste'}</strong> · {exp.company}
                      {(exp.period || exp.start_date) && (
                        <span className="muted small">
                          {' '}
                          ({exp.period || `${exp.start_date || ''} – ${exp.end_date || 'Present'}`})
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {profile.associations?.length > 0 && (
              <section className="app-drawer-sec">
                <h3>Associations &amp; clubs</h3>
                <div className="app-tag-cloud">
                  {profile.associations.map((a) => (
                    <span key={a} className="app-tag">{a}</span>
                  ))}
                </div>
              </section>
            )}

            {profile.passions?.length > 0 && (
              <section className="app-drawer-sec">
                <h3>Centres d’intérêt</h3>
                <div className="app-tag-cloud">
                  {profile.passions.map((p) => (
                    <span key={p} className="app-tag warm">{p}</span>
                  ))}
                </div>
              </section>
            )}

            {(profile.email || profile.linkedin_url) && (
              <section className="app-drawer-sec">
                <h3>Coordonnées</h3>
                <div className="app-links-row">
                  {profile.linkedin_url && (
                    <a
                      className="btn ghost app-btn-sm"
                      href={profile.linkedin_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Voir LinkedIn
                    </a>
                  )}
                  {profile.email && <span className="muted small">{profile.email}</span>}
                </div>
              </section>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}
