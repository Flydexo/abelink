import { useState } from 'react'
import { importLinkedInArchive } from '../api.js'

export default function LinkedInTab({ activeUser, onImported }) {
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [promoYear, setPromoYear] = useState('')
  const [associations, setAssociations] = useState('')
  const [passions, setPassions] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!file) {
      setError('Sélectionnez un fichier .zip d’export LinkedIn ou Connections.csv.')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (fullName.trim()) fd.append('full_name', fullName.trim())
      if (email.trim()) fd.append('email', email.trim())
      if (promoYear.trim()) fd.append('promo_year', promoYear.trim())
      if (associations.trim()) fd.append('associations', associations.trim())
      if (passions.trim()) fd.append('passions', passions.trim())

      const result = await importLinkedInArchive(fd, activeUser?.id)
      setSummary(result)
      onImported?.(result)
    } catch (err) {
      setError(err.message || 'Échec de l’import LinkedIn.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="app-panel">
      <div className="app-panel-head">
        <h2>Importer votre archive LinkedIn</h2>
        <p className="muted">
          Téléversez l’archive officielle LinkedIn (.zip) ou le fichier <code>Connections.csv</code> pour créer des liens directs à 95&nbsp;% et recalculer les chemins du graphe pour <strong>{activeUser?.full_name || 'l’étudiant actif'}</strong>.
        </p>
      </div>

      <form className="app-import-grid" onSubmit={handleSubmit}>
        <div>
          <label
            className={`app-dropzone${dragging ? ' dragging' : ''}${file ? ' has-file' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              const dropped = e.dataTransfer.files?.[0]
              if (dropped) setFile(dropped)
            }}
          >
            <input
              type="file"
              accept=".zip,.csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 16V4m0 0l-4 4m4-4l4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
            <strong>{file ? file.name : 'Glissez-déposez votre export LinkedIn'}</strong>
            <span className="muted small">
              {file
                ? `${Math.max(1, Math.round(file.size / 1024))} Ko · prêt pour l’import`
                : 'Formats acceptés : .zip (Connections, Positions, Education) ou Connections.csv'}
            </span>
          </label>
        </div>

        <div className="app-form-fields">
          <div className="app-field-row">
            <label>
              Nom complet (optionnel)
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder={activeUser?.full_name || 'Léo Bernard'}
              />
            </label>
            <label>
              Promotion
              <input
                type="number"
                value={promoYear}
                onChange={(e) => setPromoYear(e.target.value)}
                placeholder={activeUser?.promo_year ? String(activeUser.promo_year) : '2026'}
              />
            </label>
          </div>
          <label>
            Email (optionnel)
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="prenom.nom@student-cs.fr"
            />
          </label>
          <label>
            Associations à ajouter (séparées par des virgules)
            <input
              value={associations}
              onChange={(e) => setAssociations(e.target.value)}
              placeholder="BDS, Club Énergie, ViaRézo"
            />
          </label>
          <label>
            Passions à ajouter
            <input
              value={passions}
              onChange={(e) => setPassions(e.target.value)}
              placeholder="trail, énergie décarbonée, IA"
            />
          </label>

          {error && <p className="form-error" role="alert">{error}</p>}

          <button type="submit" className="btn primary" disabled={submitting}>
            {submitting ? 'Import et recalcul du graphe…' : 'Importer et mettre à jour le graphe'}
          </button>
        </div>
      </form>

      {summary && (
        <div className="app-import-result">
          <h3>Import appliqué sur {summary.full_name}</h3>
          <div className="app-stat-grid">
            <div className="app-stat">
              <strong>{summary.connections_parsed}</strong>
              <span>Connexions lues</span>
            </div>
            <div className="app-stat">
              <strong>{summary.profiles_matched}</strong>
              <span>Alumni matchés</span>
            </div>
            <div className="app-stat">
              <strong>{summary.explicit_edges_created}</strong>
              <span>Liens directs (95&nbsp;%)</span>
            </div>
            <div className="app-stat">
              <strong>{summary.inferred_edges_created}</strong>
              <span>Liens inférés</span>
            </div>
            <div className="app-stat">
              <strong>{summary.experiences_imported}</strong>
              <span>Expériences</span>
            </div>
            <div className="app-stat">
              <strong>{summary.educations_imported}</strong>
              <span>Formations</span>
            </div>
          </div>
          {summary.unmatched_sample?.length > 0 && (
            <p className="muted small">
              Exemples hors annuaire actuel : {summary.unmatched_sample.join(', ')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
