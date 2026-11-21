import { useEffect, useRef, useState } from 'react'
import { motion, animate, useInView } from 'motion/react'
import { scenarios, match, initials } from './data.js'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const STEP_MS = [800, 1800, 1200, 1300, 900]
const SUGGESTIONS = scenarios.map((s) => s.query)
const fr = (n) => n.toLocaleString('fr-FR')

function useWide() {
  const q = '(min-width: 760px)'
  const [w, setW] = useState(() => matchMedia(q).matches)
  useEffect(() => {
    const m = matchMedia(q)
    const f = () => setW(m.matches)
    m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [])
  return w
}

function Typing({ text, speed = 16 }) {
  const [n, setN] = useState(0)
  useEffect(() => {
    setN(0)
    const t = setInterval(() => setN((v) => (v >= text.length ? (clearInterval(t), v) : v + 1)), speed)
    return () => clearInterval(t)
  }, [text, speed])
  return text.slice(0, n)
}

function Count({ to }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    const c = animate(0, to, { duration: 1.6, ease: 'easeOut', onUpdate: (x) => setV(Math.round(x)) })
    return () => c.stop()
  }, [to])
  return fr(v)
}

const Mark = () => <span className="agent-mark" aria-hidden="true" />

function stepsFor(s) {
  return [
    { doing: 'J’analyse votre demande…', done: s.parse },
    {
      doing: <>Je cherche sur LinkedIn… <span className="count"><Count to={s.count} /> profils scannés</span></>,
      done: `${fr(s.count)} profils pertinents repérés`,
      chips: s.chips,
    },
    { doing: 'Je parcours le réseau alumni…', done: s.alumni },
    { doing: 'Je regarde leurs expériences passées…', done: s.exp },
    { doing: 'Je cherche le chemin le plus court depuis vos contacts…', done: '3 chemins possibles' },
  ]
}

function Steps({ s, started, done }) {
  return (
    <ul className="live">
      {stepsFor(s).slice(0, started).map((st, i) => (
        <motion.li key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <span className={i < done ? 'ind done' : 'ind spin'} aria-hidden="true" />
          <div>
            <p>{i < done ? st.done : st.doing}</p>
            {st.chips && (
              <div className="chip-row">
                {st.chips.map((c, j) => (
                  <motion.span key={c} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.25 + j * 0.2 }}>
                    {c}
                  </motion.span>
                ))}
              </div>
            )}
          </div>
        </motion.li>
      ))}
    </ul>
  )
}

function Path({ s, wide }) {
  const nodes = [
    { name: 'Vous', meta: 'Étudiant·e', kind: 'me' },
    ...s.path.map((p) => ({ ...p, kind: 'mid' })),
    { name: s.target.name, meta: s.target.meta, why: s.last, kind: 'end' },
  ]
  return (
    <ol className="path" aria-label="Chemin vers la personne">
      {nodes.map((n, i) => (
        <motion.li key={n.name} className="node" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.28 }}>
          <span className={`avatar ${n.kind}`}>{n.kind === 'me' ? 'Moi' : initials(n.name)}</span>
          <span className="who">
            <strong>{n.name}</strong>
            <span>{n.meta}</span>
            {n.why && <em>{n.why}</em>}
          </span>
          {i < nodes.length - 1 && (
            <span className="line" aria-hidden="true">
              <motion.i
                initial={wide ? { scaleX: 0 } : { scaleY: 0 }}
                animate={wide ? { scaleX: 1 } : { scaleY: 1 }}
                transition={{ delay: i * 0.28 + 0.2, duration: 0.5 }}
              />
            </span>
          )}
        </motion.li>
      ))}
    </ol>
  )
}

function Result({ s }) {
  const wide = useWide()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(s.message)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {}
  }
  return (
    <motion.div className="result" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
      <h3>{s.target.name}</h3>
      <p className="muted">{s.target.meta}</p>
      <Path s={s} wide={wide} />
      <p className="alts"><b>Autres chemins :</b> {s.alts.join(' · ')}</p>
      <div className="cols">
        <div>
          <h4>Plan d’action</h4>
          <ol className="plan">
            {s.plan.map(([when, text]) => (
              <li key={when}><span>{when}</span>{text}</li>
            ))}
          </ol>
        </div>
        <div>
          <h4>Message d’introduction</h4>
          <blockquote>{s.message}</blockquote>
          <button className="btn ghost" onClick={copy}>{copied ? 'Copié' : 'Copier le message'}</button>
        </div>
      </div>
    </motion.div>
  )
}

export default function Demo() {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-25% 0px' })
  const [query, setQuery] = useState('')
  const [run, setRun] = useState(null) // { s, exact, greet, started, done, final, result }
  const runId = useRef(0)
  const touched = useRef(false)

  useEffect(() => () => { runId.current++ }, [])

  async function start(q, id = ++runId.current) {
    if (!q.trim()) return
    const alive = () => runId.current === id
    const { scenario: s, exact } = match(q)
    const set = (p) => setRun((r) => ({ ...r, ...p }))
    setRun({ s, exact, greet: false, started: 0, done: 0, final: false, result: false })
    await sleep(350); if (!alive()) return
    set({ greet: true })
    await sleep(1300); if (!alive()) return
    for (let i = 0; i < STEP_MS.length; i++) {
      set({ started: i + 1 })
      await sleep(STEP_MS[i]); if (!alive()) return
      set({ done: i + 1 })
      await sleep(180); if (!alive()) return
    }
    set({ final: true })
    await sleep(1500); if (!alive()) return
    set({ result: true })
  }

  // Au premier affichage : saisie automatique du premier exemple, sauf si l'utilisateur prend la main.
  useEffect(() => {
    if (!inView || touched.current) return
    const id = ++runId.current
    const text = scenarios[0].query
    ;(async () => {
      for (let i = 1; i <= text.length; i++) {
        await sleep(28); if (runId.current !== id) return
        setQuery(text.slice(0, i))
      }
      await sleep(400); if (runId.current !== id) return
      start(text, id)
    })()
  }, [inView])

  const take = () => { touched.current = true; runId.current++ }
  const submit = (q) => { touched.current = true; setQuery(q); start(q) }

  return (
    <section id="demo" className="section demo" ref={ref}>
      <div className="wrap">
        <form className="search" onSubmit={(e) => { e.preventDefault(); submit(query) }} role="search">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.8" />
            <path d="M14 14l4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            value={query}
            onChange={(e) => { take(); setQuery(e.target.value) }}
            onFocus={take}
            placeholder="Décrivez ce que vous cherchez…"
            aria-label="Décrivez ce que vous cherchez"
          />
          <button className="btn primary" type="submit">Rechercher</button>
        </form>
        <div className="chips">
          {SUGGESTIONS.map((c) => (
            <button key={c} type="button" className="chip" onClick={() => submit(c)}>{c}</button>
          ))}
        </div>

        <div className="stage" aria-live="polite">
          {run && (
            <div className="agent">
              <div className="agent-row">
                <Mark />
                <div className="agent-body">
                  {!run.exact && <p className="muted small">Je n’ai pas bien compris, je pars sur l’exemple le plus proche.</p>}
                  <p className="say">{run.greet && <Typing text="Ok, je commence à chercher." />}</p>
                  <Steps s={run.s} started={run.started} done={run.done} />
                  {run.final && <p className="say"><Typing text={run.s.final} speed={12} /></p>}
                </div>
              </div>
              {run.result && <Result s={run.s} />}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
