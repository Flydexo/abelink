import { useState } from 'react'
import { motion } from 'motion/react'
import Demo from './Demo.jsx'
import DemoSheet from './DemoSheet.jsx'

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
  ['Ouvrez la bonne porte.', 'Étudiants, ne cherchez plus un nom au hasard : trouvez qui, dans le réseau, peut réellement vous présenter à la personne qui vous intéresse.'],
  ['Valorisez votre réseau.', 'Alumni, faites de vos liens un levier concret : aidez les étudiants qui vous ressemblent, en quelques minutes et à votre rythme.'],
  ['Provoquez la chance de vos étudiants.', 'Associations, offrez à chaque étudiant l’accès au réseau, pas seulement à ceux qui savent déjà à qui écrire.'],
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
          <button aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}>
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
  const [demo, setDemo] = useState(false)
  const openDemo = () => setDemo(true)
  const Cta = () => <button className="btn primary" onClick={openDemo}>Demander une démo</button>

  return (
    <div id="top">
      <header className="nav">
        <div className="nav-in">
          <Logo />
          <nav aria-label="Principal">
            <a href="#demo">En action</a><a href="#comment">Fonctionnement</a><a href="#pour-qui">Pour qui</a><a href="#faq">FAQ</a>
          </nav>
          <button className="btn small" onClick={openDemo}>Demander une démo</button>
        </div>
      </header>

      <main>
        <section className="hero">
          <div className="wrap">
            <motion.h1 initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
              Exploitez votre réseau<br />à son <span className="mark">plein potentiel.</span>
            </motion.h1>
            <motion.p className="lead" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
              Décrivez ce que vous cherchez. Abelink explore LinkedIn et votre réseau alumni, puis vous montre le chemin le plus court vers la bonne personne.
            </motion.p>
            <motion.div className="actions" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
              <Cta /><a className="btn ghost" href="#demo">Voir en action</a>
            </motion.div>
          </div>
        </section>

        <Demo />

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
            <Reveal><h2>Votre prochaine rencontre est déjà dans votre réseau.</h2><Cta /></Reveal>
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
