import { useState } from 'react'
import { motion } from 'motion/react'
import { track } from './analytics.js'

const STRIPE_WAITLIST_URL = (import.meta.env.VITE_STRIPE_WAITLIST_URL || 'https://buy.stripe.com/9B6eV6ejxdS73KY5gu1gs00').trim()

const BENEFITS = [
  'Place réservée en priorité sur la waitlist élèves',
  'Accès dès l’ouverture à la recherche de chemins alumni',
  'Messages d’introduction personnalisés prêts à envoyer',
  'Remboursé sur simple demande si ton école n’est pas encore couverte',
]

const WAITLIST_FAQ = [
  [
    'Pourquoi demander 1 € pour rejoindre la waitlist ?',
    'Ce euro symbolique permet de réserver ta place en priorité et de confirmer que tu es un étudiant réellement intéressé, pas un bot.',
  ],
  [
    'Est-ce un abonnement ?',
    'Non. C’est un paiement unique de 1 € via Stripe. Aucun prélèvement automatique ne suivra.',
  ],
  [
    'Que se passe-t-il après le paiement ?',
    'Tu reçois ton reçu Stripe par email et tu es inscrit en tête de liste. Dès que ton campus ou ton réseau est activé, tu reçois ton accès en avant-première.',
  ],
]

function buildStripeUrl(baseUrl, email) {
  const url = new URL(baseUrl)
  if (email) url.searchParams.set('prefilled_email', email)
  return url.toString()
}

export default function WaitlistPage({ onNavigateHome }) {
  const [email, setEmail] = useState('')
  const [missingConfig, setMissingConfig] = useState(false)

  const params = new URLSearchParams(window.location.search)
  const isSuccess =
    params.get('paiement') === 'succes' ||
    params.get('success') === 'true' ||
    params.get('status') === 'success'

  function handleCheckout(e) {
    e.preventDefault()
    const trimmedEmail = email.trim()
    track('waitlist_checkout_clicked', { price_eur: 1, has_email: Boolean(trimmedEmail) })

    if (!STRIPE_WAITLIST_URL) {
      setMissingConfig(true)
      return
    }

    setMissingConfig(false)
    window.location.assign(buildStripeUrl(STRIPE_WAITLIST_URL, trimmedEmail))
  }

  return (
    <main className="waitlist-main">
      <section className="hero waitlist-hero">
        <div className="wrap">
          <motion.span
            className="eyebrow"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
          >
            Accès anticipé · Élèves
          </motion.span>
          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
          >
            Décroche ton stage grâce à ton <span className="mark">réseau alumni.</span>
          </motion.h1>
          <motion.p
            className="lead"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
          >
            Réserve ta place sur la waitlist Abelink pour 1 € et sois parmi les premiers étudiants à trouver le bon chemin d’introduction vers les anciens de ton école.
          </motion.p>
        </div>
      </section>

      <section className="waitlist-section">
        <div className="wrap narrow">
          {isSuccess ? (
            <motion.div
              className="checkout-card checkout-success"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <span className="status-badge">Paiement confirmé · 1 €</span>
              <h2>Tu es sur la waitlist !</h2>
              <p className="muted">
                Merci pour ta réservation. Ton paiement de 1 € a bien été pris en compte par Stripe. Nous te contacterons par email dès l’ouverture de ton accès prioritaire.
              </p>
              <a
                className="btn primary"
                href="/"
                onClick={(e) => {
                  e.preventDefault()
                  onNavigateHome()
                }}
              >
                Retour à l’accueil
              </a>
            </motion.div>
          ) : (
            <motion.div
              className="checkout-card"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.16 }}
            >
              <div className="checkout-head">
                <div>
                  <span className="checkout-kicker">Pass Waitlist Élève</span>
                  <h2>Accès prioritaire Abelink</h2>
                </div>
                <div className="price-tag" aria-label="Prix : 1 euro">
                  <span className="price-amount">1 €</span>
                  <span className="price-note">paiement unique</span>
                </div>
              </div>

              <ul className="benefit-list">
                {BENEFITS.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>

              <form className="checkout-form" onSubmit={handleCheckout}>
                <label>
                  <span>Ton email étudiant <span className="muted">(optionnel)</span></span>
                  <input
                    type="email"
                    name="email"
                    autoComplete="email"
                    placeholder="prenom.nom@ecole.fr"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </label>

                {missingConfig && (
                  <p className="form-error" role="alert">
                    Lien de paiement Stripe non configuré. Définis <code>VITE_STRIPE_WAITLIST_URL</code> avec ton Stripe Payment Link à 1 €.
                  </p>
                )}

                <button className="btn primary wide checkout-cta" type="submit">
                  Rejoins la waitlist
                </button>
              </form>

              <p className="form-privacy">Votre email optionnel sert à préremplir le paiement Stripe. <a href="/confidentialite">Consulter la politique de confidentialité</a>.</p>
              <p className="stripe-note">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M7 10V7a5 5 0 0 1 10 0v3m-9 0h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                Paiement sécurisé de 1 € par Stripe · CB, Apple Pay, Google Pay
              </p>
            </motion.div>
          )}
        </div>
      </section>

      <section className="section waitlist-faq">
        <div className="wrap narrow">
          <h2>Questions sur la waitlist</h2>
          <div className="faq">
            {WAITLIST_FAQ.map(([q, a]) => (
              <div key={q} className="faq-item static">
                <h3>{q}</h3>
                <p>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  )
}
