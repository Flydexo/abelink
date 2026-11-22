import { useRef, useState } from 'react'
import { importAbelinkBundle, importLinkCSDump } from '../api.js'

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const MAX_RECORDS = 5000
const MAX_BUNDLE_BYTES = 1024 * 1024 * 1024
const formatMiB = (size) => `${(size / 1024 / 1024).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} Mio`

export default function LinkCSTab({ onImported, publicAccess = false }) {
  const [file, setFile] = useState(null)
  const [format, setFormat] = useState(null)
  const [uploaded, setUploaded] = useState(0)
  const [recordCount, setRecordCount] = useState(0)
  const [importToken, setImportToken] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [reading, setReading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState(null)
  const fileInput = useRef(null)
  const selection = useRef(0)
  const busy = reading || submitting
  const needsKey = !publicAccess || format === 'bundle'

  async function selectFile(selected) {
    if (busy || !selected) return
    const currentSelection = ++selection.current
    setFile(null)
    setFormat(null)
    setUploaded(0)
    setRecordCount(0)
    setSummary(null)
    setError('')
    setConfirmed(false)
    if (!selected.name.toLowerCase().endsWith('.json')) {
      setError('Sélectionnez un fichier au format .json.')
      return
    }
    if (selected.size > MAX_BUNDLE_BYTES) {
      setError('Le fichier dépasse la limite de 1 Gio.')
      return
    }
    setReading(true)
    try {
      const firstChar = (await selected.slice(0, 64 * 1024).text()).trimStart()[0]
      if (currentSelection !== selection.current) return
      if (firstChar === '{') {
        setFile(selected)
        setFormat('bundle')
        return
      }
      if (firstChar !== '[') throw new Error('Sélectionnez un export Abelink v1 ou une liste LinkCS valide.')
      if (selected.size > MAX_UPLOAD_BYTES) throw new Error('Une liste LinkCS ne peut pas dépasser 10 Mio.')
      const rows = JSON.parse((await selected.text()).replace(/^\uFEFF/, ''))
      if (currentSelection !== selection.current) return
      if (!Array.isArray(rows) || !rows.length || rows.some((row) => !row || typeof row !== 'object' || Array.isArray(row))) {
        throw new Error('Le dump doit être une liste non vide d’objets LinkCS.')
      }
      if (rows.length > MAX_RECORDS) {
        throw new Error('Le fichier dépasse la limite de 5 000 entrées. Importez un extrait plus petit.')
      }
      setFile(selected)
      setFormat('linkcs')
      setRecordCount(rows.length)
    } catch (err) {
      if (currentSelection === selection.current) {
        setError(err instanceof SyntaxError ? 'Le fichier ne contient pas de JSON valide.' : err.message)
      }
    } finally {
      if (currentSelection === selection.current) setReading(false)
    }
  }

  async function handleSubmit(event) {
    event.preventDefault()
    if (!file || !confirmed || (needsKey && !importToken.trim()) || busy) return
    setSubmitting(true)
    setError('')
    setSummary(null)
    setUploaded(0)
    try {
      const result = format === 'bundle'
        ? await importAbelinkBundle(file, importToken.trim(), setUploaded)
        : await importLinkCSDump(file, needsKey ? importToken.trim() : null)
      setSummary(result)
      setImportToken('')
      setConfirmed(false)
      onImported?.(result)
    } catch (err) {
      setError(err.message || 'Échec de l’import LinkCS. Vérifiez la clé et le fichier.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="app-panel" aria-labelledby="linkcs-title">
      <div className="app-panel-head">
        <h2 id="linkcs-title">Importer des données</h2>
        <p className="muted">
          Ajoutez des profils et des relations à partir d’un export de la base Abelink ou d’un fichier LinkCS.
          Les profils existants et leurs enrichissements sont conservés. Aucun appel IA payant n’est lancé par cet import.
        </p>
      </div>

      <form className="app-import-grid" onSubmit={handleSubmit} aria-busy={busy}>
        <div>
          <div
            className={`app-dropzone${dragging ? ' dragging' : ''}${file ? ' has-file' : ''}`}
            onDragOver={(event) => {
              event.preventDefault()
              if (!busy) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              if (!busy) selectFile(event.dataTransfer.files?.[0])
            }}
          >
            <input
              ref={fileInput}
              type="file"
              accept=".json,application/json"
              disabled={busy}
              aria-label="Choisir le fichier JSON"
              onChange={(event) => {
                selectFile(event.target.files?.[0])
                event.target.value = ''
              }}
            />
            <strong>{file ? file.name : 'Glissez votre fichier JSON ici'}</strong>
            <span className="muted small" role="status">
              {reading ? 'Vérification du fichier…' : file
                ? `${format === 'bundle' ? 'Export Abelink' : `${recordCount.toLocaleString('fr-FR')} entrées LinkCS`} · ${formatMiB(file.size)}`
                : 'Export Abelink : 1 Gio maximum · Liste LinkCS : 10 Mio maximum'}
            </span>
            <button type="button" className="btn ghost" disabled={busy} onClick={() => fileInput.current?.click()}>
              Choisir un fichier
            </button>
          </div>
          <details className="app-linkcs-format">
            <summary>Voir les formats acceptés</summary>
            <p className="muted small">
              Export Abelink : le fichier JSON v1 créé par <code>scripts.export_import_bundle</code>,
              avec <code>version</code>, <code>profiles</code> et <code>edges</code>. Aucune conversion nécessaire.
            </p>
            <p className="muted small">
              LinkCS : une liste d’objets contenant <code>nom_complet</code> ou <code>prenom</code> et <code>nom</code> (5 000 entrées maximum).
              Les champs usuels LinkCS sont reconnus : login, promotion, emails, associations, clubs, biographie et réseaux sociaux.
            </p>
            <pre className="app-code-block">{JSON.stringify([
              { login: 'exemple-fictif', nom_complet: 'Camille Exemple', promotion: 2024, associations: ['Club Tech'], reseaux_sociaux: [] },
            ], null, 2)}</pre>
          </details>
        </div>

        <div className="app-form-fields">
          {!needsKey ? (
            <p className="muted small">Import ouvert à tous, sans compte ni clé. Les données ajoutées sont partagées avec tous les visiteurs.</p>
          ) : (
            <>
          <label htmlFor="linkcs-import-token">
            Clé d’administration d’import
            <input
              id="linkcs-import-token"
              type="password"
              autoComplete="off"
              required
              disabled={submitting}
              value={importToken}
              onChange={(event) => setImportToken(event.target.value)}
              aria-describedby="linkcs-token-help"
            />
          </label>
          <p id="linkcs-token-help" className="muted small">
            Utilisez la valeur de <code>LINKCS_IMPORT_TOKEN</code> configurée dans Dokploy.
            Elle reste en mémoire dans cette page et n’est pas enregistrée dans le navigateur.
            Un export Abelink nécessite cette clé même en mode public.
          </p>
            </>
          )}
          <label className="app-import-consent">
            <input type="checkbox" checked={confirmed} disabled={busy} onChange={(event) => setConfirmed(event.target.checked)} required />
            <span>Je suis autorisé à importer ces données personnelles dans ce réseau.</span>
          </label>
          <p className="muted small">
            L’import ajoute les nouveaux profils et liens sans supprimer les données déjà présentes.
            Le fichier brut n’est pas conservé après le traitement et n’est pas transmis aux analytics.
          </p>
          {error && <p className="form-error" role="alert">{error}</p>}
          {submitting && format === 'bundle' && (
            <div role="status">
              <progress aria-label="Transfert de l’export Abelink" max={file.size} value={uploaded} />{' '}
              {uploaded < file.size ? `${formatMiB(uploaded)} / ${formatMiB(file.size)}` : 'Fichier transféré. Import et mise à jour du graphe…'}
            </div>
          )}
          <button className="btn primary" type="submit" disabled={busy || !file || !confirmed || (needsKey && !importToken.trim())}>
            {submitting ? 'Import en cours…' : 'Importer dans le réseau'}
          </button>
        </div>
      </form>

      {summary && (
        <div className="app-import-result" role="status">
          <h3>Import terminé</h3>
          <div className="app-stat-grid">
            <div className="app-stat"><strong>{summary.records_received}</strong><span>Entrées lues</span></div>
            <div className="app-stat"><strong>{summary.profiles_added}</strong><span>Profils ajoutés</span></div>
            <div className="app-stat"><strong>{summary.profiles_skipped}</strong><span>Profils existants ou doublons ignorés</span></div>
            <div className="app-stat"><strong>{summary.relationships_added}</strong><span>Liens ajoutés</span></div>
          </div>
          <p className="muted small">
            {summary.warning || (summary.storage === 'postgres'
              ? 'Les données sont enregistrées dans PostgreSQL et le graphe est à jour.'
              : 'Mode mémoire : les données importées seront perdues au redémarrage du backend.')}
          </p>
        </div>
      )}
    </section>
  )
}
