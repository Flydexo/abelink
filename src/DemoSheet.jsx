import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'

// Pas de backend : FormSubmit (service tiers) transmet la demande par email.
// Le tout premier envoi déclenche un email d'activation à cette adresse.
const ENDPOINT = 'https://formsubmit.co/ajax/gaspardobert70@gmail.com'

export default function DemoSheet({ open, onClose }) {
  const [sent, setSent] = useState(false)
  const [state, setState] = useState('idle') // idle | sending | error

  async function submit(e) {
    e.preventDefault()
    setState('sending')
    try {
      const f = Object.fromEntries(new FormData(e.currentTarget))
      const r = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ ...f, _subject: 'Demande de démo Abelink', _template: 'table', _captcha: 'false' }),
      })
      const j = await r.json()
      if (!r.ok || String(j.success) !== 'true') throw new Error(j.message)
      setSent(true)
    } catch {
      setState('error')
    }
  }

  useEffect(() => {
    if (!open) return
    setSent(false); setState('idle')
    const key = (e) => e.key === 'Escape' && onClose()
    addEventListener('keydown', key)
    document.body.style.overflow = 'hidden'
    return () => { removeEventListener('keydown', key); document.body.style.overflow = '' }
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.div
            className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title"
            initial={{ y: 60, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }} exit={{ y: 60, opacity: 0 }}
            transition={{ type: 'spring', bounce: 0.2, duration: 0.45 }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="sheet-title">Demander une démo</h2>
            {!sent ? (
              <form onSubmit={submit}>
                <p className="muted">Voyez Abelink sur votre propre réseau alumni.</p>
                <label>Nom<input name="name" autoComplete="name" required autoFocus /></label>
                <label>Email professionnel<input name="email" type="email" autoComplete="email" required /></label>
                <label>Votre réseau alumni<input name="network" required placeholder="Ex. Association des anciens de…" /></label>
                <input className="hp" name="_honey" tabIndex={-1} autoComplete="off" aria-hidden="true" />
                {state === 'error' && <p className="form-error" role="alert">L’envoi a échoué. Réessayez dans un instant.</p>}
                <button className="btn primary wide" type="submit" disabled={state === 'sending'}>
                  {state === 'sending' ? 'Envoi…' : 'Envoyer la demande'}
                </button>
              </form>
            ) : (
              <>
                <p className="muted">Merci, votre demande est bien notée. Nous revenons vers vous très vite.</p>
                <button className="btn ghost wide" onClick={onClose} autoFocus>Fermer</button>
              </>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
