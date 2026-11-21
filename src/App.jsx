import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import Demo from './Demo.jsx'
import StepIllustration from './StepIllustration.jsx'
import LegalPage from './LegalPage.jsx'
import DemoSheet from './DemoSheet.jsx'
import WaitlistPage from './WaitlistPage.jsx'
import LiveApp from './live/LiveApp.jsx'
import { track } from './analytics.js'

const isWaitlistPath = (pathname) => pathname === '/waitlist' || pathname === '/eleves'

const Logo = ({ onNavigate }) => (
  <a
    className="logo"
    href="/"
    aria-label="Abelink, accueil"
    onClick={(e) => {
      if (!onNavigate) return
      e.preventDefault()
      onNavigate('/')
    }}
  >
    Abe<span>link</span>
  </a>
)

const Reveal = ({ children, className, delay = 0 }) => (
  <motion.div className={className} initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
    viewport={{ once: true, margin: '-12% 0px' }} transition={{ delay }}>
    {children}
  </motion.div>
)

const STEPS = [
  ['Décrivez ce que vous cherchez', 'Un stage, une entreprise, un secteur. Écrivez-le comme vous le diriez à un ami : l’IA comprend l’intention.'],
  ['Laissez l’IA chercher', 'Abelink explore LinkedIn, votre réseau alumni et les expériences passées pour trouver les bonnes personnes et les contacts proches de vous qui peuvent les joindre.'],
  ['Passez à l’action', 'Un chemin clair, un plan en trois étapes et un message d’introduction prêt à envoyer à chaque contact.'],
]

const AUDIENCES = [
  ['Rendez votre réseau actionnable.', 'Donnez aux étudiants de votre association une méthode claire pour trouver les bons contacts et activer les liens alumni de façon pertinente.'],
  ['Accompagnez chaque démarche.', 'Abelink aide vos membres à formuler leur objectif, repérer les bons chemins et préparer une demande d’introduction.'],
  ['Valorisez l’engagement de vos alumni.', 'Facilitez des mises en relation utiles, à leur rythme et avec leur accord, tout en renforçant la valeur de votre association.'],
]

const FAQ = [
  ['Comment Abelink trouve-t-il les chemins ?', 'L’IA croise LinkedIn, les parcours, les associations, les promotions et les entreprises de votre réseau alumni pour proposer le chemin le plus court et le plus naturel vers la personne cherchée.'],
  ['Les alumni sont-ils sollicités sans leur accord ?', 'Non. Chaque introduction passe par un contact qui vous connaît déjà, et chaque alumni garde la main sur ce qu’il accepte de partager.'],
  ['Qui peut utiliser Abelink ?', 'Les étudiants et anciens d’un réseau alumni partenaire, ainsi que ses associations étudiantes.'],
  ['Comment démarrer ?', 'Demandez une démo : nous vous montrons Abelink sur votre propre réseau alumni.'],
]

function Faq() {
  const [open, setOpen] = useState(0)
  return (
    <div className="faq">
      {FAQ.map(([q, a], i) => (
        <div key={q} className="faq-item">
          <button aria-expanded={open === i} onClick={() => {
            const next = open === i ? -1 : i
            setOpen(next)
            if (next !== -1) track('faq_item_opened', { question_index: i + 1 })
          }}>
            {q}<span className={open === i ? 'plus open' : 'plus'} aria-hidden="true" />
          </button>
          <motion.div initial={false} animate={{ height: open === i ? 'auto' : 0, opacity: open === i ? 1 : 0 }} style={{ overflow: 'hidden' }}>
            <p>{a}</p>
          </motion.div>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname)
  const [demo, setDemo] = useState(false)
  const [demoReplay, setDemoReplay] = useState(0)

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = (to, hash = '') => {
    const targetUrl = `${to}${hash}`
    if (window.location.pathname !== to || window.location.search) {
      window.history.pushState({}, '', targetUrl)
      setPathname(to)
    }
    if (hash) {
      requestAnimationFrame(() => {
        document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth' })
      })
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  if (pathname.startsWith('/app')) {
    return <LiveApp onNavigateHome={() => navigate('/')} />
  }

  const onWaitlist = isWaitlistPath(pathname)
  const legalKind = pathname === '/confidentialite' ? 'privacy' : pathname === '/mentions-legales' ? 'legal' : null

  const openDemo = (placement = 'unknown') => {
    track('demo_request_opened', { placement })
    setDemo(true)
  }
  const replayDemo = () => {
    track('interactive_demo_replayed')
    setDemoReplay((value) => value + 1)
    document.getElementById('demo')?.scrollIntoView({ behavior: 'smooth' })
  }
  const Cta = ({ placement }) => <button className="btn primary" onClick={() => openDemo(placement)}>Demander une démo</button>

  return (
    <div id="top">
      <header className="nav">
        <div className="nav-in">
          <Logo onNavigate={navigate} />
          <nav aria-label="Principal">
            {onWaitlist || legalKind ? (
              <a href="/" onClick={(e) => { e.preventDefault(); navigate('/') }}>Accueil</a>
            ) : (
              <>
                <a href="#demo">En action</a><a href="#comment">Fonctionnement</a><a href="#pour-qui">Pour qui</a><a href="#faq">FAQ</a>
              </>
            )}
            <a href="/app" onClick={(e) => { e.preventDefault(); navigate('/app') }}>Démo live</a>
            <a
              href="/waitlist"
              className={onWaitlist ? 'nav-active' : undefined}
              onClick={(e) => {
                e.preventDefault()
                track('waitlist_page_opened', { placement: 'navigation' })
                navigate('/waitlist')
              }}
            >
              Élèves · Waitlist
            </a>
          </nav>
          {onWaitlist ? (
            <a className="btn small" href="#waitlist-checkout" onClick={(e) => { e.preventDefault(); document.querySelector('.checkout-card')?.scrollIntoView({ behavior: 'smooth' }) }}>
              Rejoins la waitlist
            </a>
          ) : (
            <button className="btn small" onClick={() => openDemo('navigation')}>Demander une démo</button>
          )}
        </div>
      </header>

      {legalKind ? (
        <LegalPage kind={legalKind} onNavigate={navigate} />
      ) : onWaitlist ? (
        <WaitlistPage onNavigateHome={() => navigate('/')} />
      ) : (
      <main>
        <section className="hero">
          <div className="wrap">
            <motion.h1 initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
              Exploitez votre réseau Alumni<br />à son <span className="mark">plein potentiel.</span>
            </motion.h1>
            <motion.p className="lead" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
              Un étudiant vise un stage dans l’énergie, mais ne connaît personne chez les entreprises qui l’intéressent. Il passe des heures sur LinkedIn à chercher qui contacter, puis envoie des candidatures à froid. Abelink repère les alumni pertinents et le chemin d’introduction.
            </motion.p>
            <motion.div className="actions" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
              <Cta placement="hero" />
              <button className="btn ghost" onClick={() => navigate('/app')}>Tester la démo complète</button>
              <button className="btn ghost" onClick={replayDemo}>Voir en action</button>
            </motion.div>
            <motion.p className="hero-student-link" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.26 }}>
              Tu es étudiant ?{' '}
              <a
                href="/waitlist"
                onClick={(e) => {
                  e.preventDefault()
                  track('waitlist_page_opened', { placement: 'hero' })
                  navigate('/waitlist')
                }}
              >
                Rejoins la waitlist pour 1 € →
              </a>
            </motion.p>
          </div>
        </section>

        <Demo replay={demoReplay} />

        <section className="section problem">
          <div className="wrap problem-layout">
            <Reveal className="problem-copy">
              <span className="section-kicker">Le bon contact change tout</span>
              <h2>Un étudiant cherche un stage.<br /><span>Qui peut le mettre en relation ?</span></h2>
              <p>Il sait où il veut aller. Pas encore à qui écrire. Entre les profils LinkedIn et l’annuaire de l’école, le bon contact reste souvent invisible.</p>
              <p>Abelink fait le lien entre son projet, les alumni pertinents et les personnes qui peuvent les présenter.</p>
              <a className="text-link" href="#demo">Voir le chemin avec Abelink <span aria-hidden="true">↗</span></a>
            </Reveal>
            <Reveal className="connection-story" delay={0.12}>
              <span className="story-label">De « je ne connais personne » à…</span>
              <div className="story-request">« Je cherche un stage de césure dans l’énergie. »</div>
              <ol className="story-path" aria-label="Exemple fictif de mise en relation">
                <li><span className="story-avatar">V</span><div><strong>Vous</strong><span>Un projet, mais pas de contact</span></div></li>
                <li><span className="story-avatar connector">HM</span><div><strong>Hugo, votre premier lien</strong><span>Le même club Énergie que vous</span></div><span className="story-tag">En commun</span></li>
                <li><span className="story-avatar destination">JM</span><div><strong>Julien, chez Engie</strong><span>Un alumni à qui parler de votre césure</span></div></li>
              </ol>
              <div className="story-outcome"><span aria-hidden="true">↳</span> Une introduction plutôt qu’une candidature à froid.</div>
              <span className="story-footnote">Exemple illustratif · chemin simplifié</span>
            </Reveal>
          </div>
        </section>

        <section id="comment" className="section how-section">
          <div className="wrap">
            <Reveal className="section-heading"><span className="section-kicker">Simple, du début à la rencontre</span><h2>Trois étapes.<br />Un chemin clair.</h2><p>Pas besoin de savoir qui chercher.<br />Commencez par ce que vous voulez faire.</p></Reveal>
            <div className="steps illustrated-steps">
              {STEPS.map(([title, description], index) => (
                <Reveal key={title} className="step" delay={index * 0.08}>
                  <StepIllustration step={index} />
                  <span className="step-index">0{index + 1}</span><h3>{title}</h3><p>{description}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section id="pour-qui" className="section audience-section">
          <div className="wrap audience-layout">
            <Reveal className="audience-intro"><span className="section-kicker">À chaque membre, son déclic</span><h2>Un réseau.<br />Trois façons<br />d’en tirer parti.</h2><p>De la première recherche à la mise en relation, chaque rôle fait vivre le réseau.</p><button className="text-link" onClick={() => openDemo('audiences')}>Parlons de votre réseau <span aria-hidden="true">↗</span></button></Reveal>
            <div className="audience-list">
              {AUDIENCES.map(([title, description], index) => (
                <Reveal key={title} className="audience-row" delay={index * 0.08}>
                  <span className="audience-number">0{index + 1}</span><div><span className="audience-role">{['Associations alumni', 'Étudiants & membres', 'Anciens & mentors'][index]}</span><h3>{title}</h3><p>{description}</p></div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section id="faq" className="section">
          <div className="wrap narrow">
            <Reveal><h2>Questions fréquentes</h2></Reveal>
            <Faq />
          </div>
        </section>

        <section className="section final">
          <div className="wrap">
            <Reveal><h2>Votre prochaine rencontre est déjà dans votre réseau.</h2><Cta placement="footer_cta" /></Reveal>
          </div>
        </section>
      </main>
      )}

      <footer className="footer">
        <div className="wrap foot-in">
          <Logo onNavigate={navigate} />
          <span>Abelink · © 2026</span>
          <span>
            <a
              href="/waitlist"
              onClick={(e) => {
                e.preventDefault()
                track('waitlist_page_opened', { placement: 'footer' })
                navigate('/waitlist')
              }}
            >
              Waitlist élèves (1 €)
            </a>
            {' · '}
            <a href="/confidentialite" onClick={(event) => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate('/confidentialite') } }}>Confidentialité</a> · <a href="/mentions-legales" onClick={(event) => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate('/mentions-legales') } }}>Mentions légales</a>
          </span>
        </div>
      </footer>

      <DemoSheet open={demo} onClose={() => setDemo(false)} />
    </div>
  )
}
