import { useEffect, useRef, useState } from 'react'
import { motion, animate, useInView } from 'motion/react'
import { scenarios, match, initials } from './data.js'
import { track } from './analytics.js'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const STEP_MS = [800, 1800, 1200, 1300, 900]
const SUGGESTIONS = scenarios.map((s) => s.query)
const fr = (n) => n.toLocaleString('fr-FR')

function useWide() {
  const q = '(min-width: 640px)'
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

function stepsFor(s) {
  return [
    {
      title: 'Analyse de la demande',
      doing: 'Lecture de votre recherche…',
      done: s.parse,
    },
    {
      title: 'Recherche sur LinkedIn',
      doing: <><span className="count"><Count to={s.count} /></span> profils scannés…</>,
      done: `${fr(s.count)} profils pertinents`,
      sub: s.chips.join(' · '),
    },
    {
      title: 'Réseau alumni',
      doing: 'Exploration de votre réseau…',
      done: s.alumni,
    },
    {
      title: 'Expériences passées',
      doing: 'Vérification des parcours…',
      done: s.exp,
    },
    {
      title: 'Calcul du chemin',
      doing: 'Recherche du chemin le plus court…',
      done: '3 chemins possibles',
    },
  ]
}

function Steps({ s, started, done }) {
  return (
    <ul className="live">
      {stepsFor(s).slice(0, started).map((st, i) => {
        const isDone = i < done
        return (
          <motion.li key={st.title} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <span className={isDone ? 'ind done' : 'ind spin'} aria-hidden="true" />
            <div className="step-text">
              <strong>{st.title}</strong>
              <p>{isDone ? st.done : st.doing}</p>
              {st.sub && isDone && (
                <motion.p className="step-sub" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                  {st.sub}
                </motion.p>
              )}
            </div>
          </motion.li>
        )
      })}
    </ul>
  )
}

function Path({ s, wide }) {
  const nodes = [
    { name: 'Vous', meta: 'Étudiant·e', kind: 'me' },
    ...s.path.map((p) => ({ ...p, kind: 'mid' })),
    { name: s.target.name, meta: s.target.shortMeta, why: s.last, kind: 'end' },
  ]
  return (
    <ol className="path" aria-label="Chemin vers la personne">
      {nodes.map((n, i) => (
        <motion.li key={n.name} className="node" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.24 }}>
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
                transition={{ delay: i * 0.24 + 0.16, duration: 0.45 }}
              />
            </span>
          )}
        </motion.li>
      ))}
    </ol>
  )
}

function TargetPanel({ s, wide }) {
  return (
    <motion.div className="result-panel" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="target-head">
        <span className="avatar end large">{initials(s.target.name)}</span>
        <div>
          <span className="target-kicker">Personne à joindre</span>
          <h3>{s.target.name}</h3>
          <p className="muted small">{s.target.meta}</p>
        </div>
      </div>

      <Path s={s} wide={wide} />

      <div className="alts-box">
        <h4>Autres chemins</h4>
        <ul className="alts-list">
          {s.alts.map(([who, meta]) => (
            <li key={who}>
              <span>{who}</span>
              <span className="muted">{meta}</span>
            </li>
          ))}
        </ul>
      </div>
    </motion.div>
  )
}

function BottomPanel({ s }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(s.message)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {}
  }

  return (
    <motion.div className="demo-bottom" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}>
      <div>
        <h4>Plan d’action</h4>
        <ol className="plan">
          {s.plan.map(([when, text], i) => (
            <li key={when}>
              <span className="plan-num" aria-hidden="true">{i + 1}</span>
              <div className="plan-body">
                <span className="plan-when">{when}</span>
                <p>{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div>
        <h4>Message d’introduction</h4>
        <blockquote>{s.message}</blockquote>
        <button type="button" className="btn ghost copy-btn" onClick={copy}>
          {copied ? (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <rect x="5.5" y="5.5" width="7.5" height="8.5" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
              <path d="M10.5 5.5V3.5A1.5 1.5 0 0 0 9 2H4.5A1.5 1.5 0 0 0 3 3.5V10a1.5 1.5 0 0 0 1.5 1.5h1" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          )}
          {copied ? 'Message copié' : 'Copier le message'}
        </button>
      </div>
    </motion.div>
  )
}

export default function Demo({ replay = 0 }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-25% 0px' })
  const wide = useWide()
  const [query, setQuery] = useState('')
  const [run, setRun] = useState(null) // { s, exact, greet, started, done, final, result }
  const runId = useRef(0)
  const touched = useRef(false)

  useEffect(() => () => { runId.current++ }, [])

  useEffect(() => {
    if (!replay) return
    touched.current = false
    runId.current++
    setRun(null)
    setQuery('')
    const id = runId.current
    const text = scenarios[0].query
    ;(async () => {
      for (let i = 1; i <= text.length; i++) {
        await sleep(28); if (runId.current !== id) return
        setQuery(text.slice(0, i))
      }
      await sleep(400); if (runId.current !== id) return
      start(text, id, 'replay')
    })()
  }, [replay])

  async function start(q, id, source = 'manual_search') {
    if (!q.trim()) return
    const currentId = id ?? ++runId.current
    setQuery('')
    track('interactive_demo_search_submitted', { source })
    const alive = () => runId.current === currentId
    const { scenario: s, exact } = match(q)
    const set = (p) => setRun((r) => ({ ...r, ...p }))
    setRun({ s, exact, query: q.trim(), greet: false, started: 0, done: 0, final: false, result: false })
    await sleep(350); if (!alive()) return
    set({ greet: true })
    await sleep(1100); if (!alive()) return
    for (let i = 0; i < STEP_MS.length; i++) {
      set({ started: i + 1 })
      await sleep(STEP_MS[i]); if (!alive()) return
      set({ done: i + 1 })
      await sleep(180); if (!alive()) return
    }
    set({ final: true })
    await sleep(1300); if (!alive()) return
    set({ result: true })
    track('interactive_demo_result_viewed', { source })
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
      start(text, id, 'autoplay')
    })()
  }, [inView])

  const take = () => { touched.current = true; if (!run) runId.current++ }
  const submit = (q, source = 'manual_search') => { touched.current = true; setQuery(q); start(q, undefined, source) }

  return (
    <section id="demo" className="section demo" ref={ref}>
      <div className="wrap">
        <div className="demo-box chat-demo">
          <div className="chat-toolbar">
            <span className="chat-brand"><span className="agent-mark" aria-hidden="true" /> Abelink</span>
            <span className="demo-label">Démo interactive · profils fictifs</span>
          </div>
          <div className="chat-thread" aria-live="polite" aria-busy={Boolean(run && !run.result)}>
            {!run && <div className="chat-welcome"><span className="section-kicker">Votre réseau, autrement</span><h2>Une envie. Une conversation.<br />Les bonnes personnes.</h2><p>Décrivez votre projet ou essayez un exemple ci-dessous.</p></div>}
            {run && (
              <div className="demo-content" key={run.query}>
                <div className="chat-user"><span className="chat-speaker">Vous</span><p>{run.query}</p></div>
                <div className="chat-assistant">
                  <div className="agent-head"><span className="agent-mark" aria-hidden="true" /><span className="chat-speaker">Abelink</span></div>
                  <p className="say">{run.greet ? <Typing text={
                    'J’explore votre réseau alumni pour trouver les personnes les plus pertinentes et les contacts qui peuvent vous présenter. Objectif : ' + run.s.parse.charAt(0).toLowerCase() + run.s.parse.slice(1) + '.'
                  } /> : 'Je prépare votre recherche…'}</p>
                  {!run.exact && <p className="muted small fallback-note">Cette démo utilise un scénario prédéfini proche de votre demande, pas une recherche réelle.</p>}
                  {run.started > 0 && (
                    <details className="chat-research" open={!run.result}>
                      <summary>{run.result ? 'Recherche terminée · voir les étapes' : 'Exploration du réseau en cours…'}</summary>
                      <Steps s={run.s} started={run.started} done={run.done} />
                    </details>
                  )}
                  {run.final && <p className="agent-summary"><Typing text={run.s.final} speed={12} /></p>}
                  {run.result && <><TargetPanel s={run.s} wide={wide} /><BottomPanel key={run.query} s={run.s} /></>}
                </div>
              </div>
            )}
          </div>
          <div className="chat-compose">
            <div className="chips" aria-label="Exemples de recherches">
              {SUGGESTIONS.map((suggestion, index) => (
                <button key={suggestion} type="button" className={
                  'chip' + (run?.s.query === suggestion ? ' active' : '')
                } onClick={() => submit(suggestion, 'suggestion')}>
                  {['Un stage dans l’énergie', 'Un échange dans la santé', 'Découvrir la finance', 'Lancer ma startup'][index] || suggestion}<span aria-hidden="true"> ↗</span>
                </button>
              ))}
            </div>
            <form className="search chat-input" onSubmit={(event) => { event.preventDefault(); submit(query) }}>
              <textarea rows={2} value={query} onChange={(event) => { take(); setQuery(event.target.value) }} onFocus={take}
                onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(query) } }}
                placeholder="Je cherche un stage de césure dans une boîte qui travaille dans l’énergie…" aria-label="Votre message à Abelink" />
              <button className="chat-send" type="submit" disabled={!query.trim()} aria-label="Envoyer le message">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </button>
            </form>
            <p className="chat-disclaimer">Un aperçu du fonctionnement d’Abelink. Aucun compte connecté, aucun message envoyé.</p>
          </div>
        </div>
      </div>
    </section>
  )
}
