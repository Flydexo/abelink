import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import Demo from './Demo.jsx'
import DemoSheet from './DemoSheet.jsx'
import LiveApp from './live/LiveApp.jsx'
import { track } from './analytics.js'

const Logo = () => (
  <a className="logo" href="#top" aria-label="Abelink, accueil">Abe<span>link</span></a>
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
  const [route, setRoute] = useState(() =>
    typeof window !== 'undefined' && window.location.pathname.startsWith('/app') ? '/app' : '/',
  )
  const [demo, setDemo] = useState(false)
  const [demoReplay, setDemoReplay] = useState(0)

  useEffect(() => {
    const onPop = () => {
      setRoute(window.location.pathname.startsWith('/app') ? '/app' : '/')
    }
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [])

  const navigate = (to) => {
    if (window.location.pathname !== to) {
      window.history.pushState({}, '', to)
    }
    setRoute(to)
    window.scrollTo({ top: 0 })
  }

  if (route === '/app') {
    return <LiveApp onNavigateHome={() => navigate('/')} />
  }

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
          <Logo />
          <nav aria-label="Principal">
            <a href="#demo">En action</a><a href="#comment">Fonctionnement</a><a href="#pour-qui">Pour qui</a><a href="#faq">FAQ</a>
            <a href="/app" onClick={(e) => { e.preventDefault(); navigate('/app') }}>Démo live</a>
          </nav>
          <button className="btn small" onClick={() => navigate('/app')}>Ouvrir l’app</button>
        </div>
      </header>

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
          </div>
        </section>

        <Demo replay={demoReplay} />

        <section className="section problem">
          <div className="wrap">
            <Reveal><h2>Un étudiant cherche un stage. Qui peut le mettre en relation&nbsp;?</h2></Reveal>
            <Reveal><p className="lead">Pour les responsables d’associations alumni, la situation est familière : un étudiant de l’école cherche un stage de césure dans l’énergie, mais ne sait pas quel ancien contacter chez Engie ou EDF. Il passe ses soirées à parcourir LinkedIn, hésite à écrire à des inconnus et risque de laisser passer des pistes faute d’introduction.</p></Reveal>
            <div className="cards problem-quotes">
              <Reveal className="card"><p>« Je cherche un stage dans l’énergie : quel alumni peut me conseiller ? »</p></Reveal>
              <Reveal className="card" delay={0.08}><p>« J’ai passé des heures sur LinkedIn sans trouver à qui écrire. »</p></Reveal>
            </div>
            <Reveal><p>Abelink transforme les parcours de votre réseau en pistes concrètes : les bons alumni, les liens qui vous rapprochent et une demande d’introduction à envoyer.</p></Reveal>
          </div>
        </section>

        <section id="comment" className="section">
          <div className="wrap">
            <Reveal><h2>Trois étapes. Un chemin clair.</h2></Reveal>
            <div className="steps">
              {STEPS.map(([t, d], i) => (
                <Reveal key={t} className="step" delay={i * 0.08}><h3>{t}</h3><p>{d}</p></Reveal>
              ))}
            </div>
          </div>
        </section>

        <section id="pour-qui" className="section tint">
          <div className="wrap">
            <Reveal><h2>Un réseau. Trois façons d’en tirer parti.</h2></Reveal>
            <div className="cards">
              {AUDIENCES.map(([h, d], i) => (
                <Reveal key={h} className="card" delay={i * 0.08}><h3>{h}</h3><p>{d}</p></Reveal>
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

      <footer className="footer">
        <div className="wrap foot-in">
          <Logo />
          <span>Abelink · © 2026</span>
          <span><a href="#top">Confidentialité</a> · <a href="#top">Mentions légales</a></span>
        </div>
      </footer>

      <DemoSheet open={demo} onClose={() => setDemo(false)} />
    </div>
  )
}
