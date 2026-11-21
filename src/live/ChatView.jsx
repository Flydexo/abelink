import { useEffect, useRef, useState } from 'react'
import { streamChat } from '../api.js'
import { track } from '../analytics.js'
import ContactChainCard from './ContactChainCard.jsx'
import PeopleTable from './PeopleTable.jsx'
import ToolTrace from './ToolTrace.jsx'

const STARTER_PROMPTS = [
  "Je cherche un stage de césure dans l'énergie chez EDF ou Engie",
  "Qui travaille dans l'IA générative ou le machine learning ?",
  "Trouve des alumni dans l'aérospatial ou les CubeSat",
]

function formatTimeLabel(date = new Date()) {
  return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function renderInlineBold(line, keyPrefix) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`${keyPrefix}-b-${idx}`}>{part.slice(2, -2)}</strong>
    }
    return part
  })
}

function ProseContent({ text, paragraphClass = 'chat-assistant-intro' }) {
  if (!text) return null
  const blocks = String(text)
    .trim()
    .split(/\n{2,}/)
    .filter(Boolean)

  if (blocks.length === 0) return null

  return (
    <div className="chat-assistant-prose">
      {blocks.map((block, bIdx) => {
        const lines = block
          .split('\n')
          .map((l) => l.trimEnd())
          .filter((l) => l.trim().length > 0)
        const isBulletList =
          lines.length > 0 && lines.every((l) => /^[-*•]\s+/.test(l.trim()))

        if (isBulletList) {
          return (
            <ul key={`b-${bIdx}`} className="chat-assistant-list">
              {lines.map((line, lIdx) => (
                <li key={`b-${bIdx}-l-${lIdx}`}>
                  {renderInlineBold(line.trim().replace(/^[-*•]\s+/, ''), `b-${bIdx}-l-${lIdx}`)}
                </li>
              ))}
            </ul>
          )
        }

        return (
          <p key={`b-${bIdx}`} className={paragraphClass}>
            {lines.map((line, lIdx) => (
              <span key={`b-${bIdx}-p-${lIdx}`}>
                {lIdx > 0 && <br />}
                {renderInlineBold(line, `b-${bIdx}-p-${lIdx}`)}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}

export default function ChatView({ activeUser, activeUserId, onSelectPerson }) {
  const [thread, setThread] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState(null)

  const abortRef = useRef(null)
  const endRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    abortRef.current?.abort()
    setThread([])
    setError('')
    setStreaming(false)
  }, [activeUserId])

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thread, streaming])

  function adjustTextareaHeight() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`
  }

  async function copyText(id, text) {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      setTimeout(() => {
        setCopiedId((prev) => (prev === id ? null : prev))
      }, 1800)
    } catch {}
  }

  async function submitMessage(rawText) {
    const content = rawText.trim()
    if (!content || streaming) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const userMsgId = `u-${Date.now()}`
    const assistantMsgId = `a-${Date.now() + 1}`
    const timestamp = formatTimeLabel()

    const apiHistory = [
      ...thread.map((item) => ({
        role: item.role,
        content:
          item.role === 'user'
            ? item.content
            : [item.intro_text, item.outro_text].filter(Boolean).join('\n\n') || item.content || '',
        timestamp: item.timestamp || null,
      })),
      { role: 'user', content, timestamp },
    ]

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setError('')
    setStreaming(true)

    setThread((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content, timestamp },
      {
        id: assistantMsgId,
        role: 'assistant',
        intro_text: '',
        outro_text: '',
        tools_used: [],
        total_duration_ms: 0,
        total_candidates: 0,
        people: [],
        drafted_message: null,
        running: true,
      },
    ])

    track('chat_turn_sent', { turn_count: apiHistory.length })

    const updateAssistant = (updater) => {
      setThread((prev) =>
        prev.map((msg) => (msg.id === assistantMsgId ? updater(msg) : msg)),
      )
    }

    try {
      const finalRes = await streamChat(
        apiHistory,
        activeUserId,
        (evName, payload) => {
          if (evName === 'assistant_intro') {
            updateAssistant((m) => ({ ...m, intro_text: payload.intro_text || '' }))
          } else if (evName === 'tool_start') {
            updateAssistant((m) => ({
              ...m,
              tools_used: [
                ...m.tools_used.filter((t) => t.id !== payload.id),
                {
                  id: payload.id,
                  tool: payload.tool,
                  label: payload.label,
                  detail: payload.detail || '',
                  status: 'running',
                  duration_ms: 0,
                  count: null,
                },
              ],
            }))
          } else if (evName === 'tool_done') {
            updateAssistant((m) => ({
              ...m,
              tools_used: m.tools_used.some((t) => t.id === payload.id)
                ? m.tools_used.map((t) => (t.id === payload.id ? payload : t))
                : [...m.tools_used, payload],
            }))
          } else if (evName === 'final_result') {
            const resp = payload?.response || payload?.data?.response
            if (resp) {
              updateAssistant((m) => ({
                ...m,
                intro_text: resp.intro_text || m.intro_text,
                outro_text: resp.outro_text || '',
                tools_used: resp.tools_used || m.tools_used,
                total_duration_ms: resp.total_duration_ms || 0,
                total_candidates: resp.total_candidates || 0,
                people: resp.people || [],
                drafted_message: resp.drafted_message || null,
                running: false,
              }))
            }
          }
        },
        controller.signal,
      )

      if (finalRes) {
        updateAssistant((m) => ({
          ...m,
          intro_text: finalRes.intro_text || m.intro_text,
          outro_text: finalRes.outro_text || '',
          tools_used: finalRes.tools_used || m.tools_used,
          total_duration_ms: finalRes.total_duration_ms || 0,
          total_candidates: finalRes.total_candidates || 0,
          people: finalRes.people || [],
          drafted_message: finalRes.drafted_message || null,
          running: false,
        }))
      } else {
        updateAssistant((m) => ({ ...m, running: false }))
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        updateAssistant((m) => ({
          ...m,
          intro_text: m.intro_text || 'Recherche interrompue.',
          tools_used: m.tools_used.map((tool) => tool.status === 'running'
            ? { ...tool, status: 'cancelled', detail: 'Recherche interrompue.' }
            : tool),
          running: false,
        }))
      } else {
        setError(err.message || 'Impossible de joindre l’agent réseau.')
        updateAssistant((m) => ({
          ...m,
          intro_text: m.intro_text || 'Une erreur est survenue lors de l’exécution.',
          tools_used: m.tools_used.map((tool) => tool.status === 'running'
            ? { ...tool, status: 'error', detail: 'Cette étape a échoué. Veuillez réessayer.' }
            : tool),
          running: false,
        }))
      }
    } finally {
      setStreaming(false)
    }
  }

  function handleDraftIntro(person, mutual) {
    if (streaming) return
    const prompt = mutual
      ? `Rédige un message à ${mutual.full_name} pour qu'il me présente ${person.full_name}`
      : `Rédige un message direct pour contacter ${person.full_name}`
    submitMessage(prompt)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submitMessage(input)
    }
  }

  function handleAbort() {
    abortRef.current?.abort()
  }

  function handleReset() {
    abortRef.current?.abort()
    setThread([])
    setError('')
    setStreaming(false)
    textareaRef.current?.focus()
  }

  return (
    <div className="chat-shell">
      <div className="chat-scroll">
        {thread.length === 0 ? (
          <section className="chat-empty">
            <h1 className="chat-empty-title">
              Interrogez le réseau CentraleSupélec{activeUser?.full_name ? `, ${activeUser.full_name.split(' ')[0]}` : ''}
            </h1>
            <p className="chat-empty-sub">
              Décrivez un secteur, une entreprise, le prénom d’un camarade ou demandez une introduction :
              Abelink explore l’annuaire, vérifie les contacts communs et rédige vos messages.
            </p>

            <div className="chat-starters" role="group" aria-label="Exemples de demandes">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="chat-starter-chip"
                  onClick={() => submitMessage(prompt)}
                >
                  <span>{prompt}</span>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M3.5 8h9M9 4.5L12.5 8 9 11.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              ))}
            </div>
          </section>
        ) : (
          <div className="chat-thread" aria-live="polite">
            {thread.map((msg) =>
              msg.role === 'user' ? (
                <article key={msg.id} className="chat-turn-user">
                  <div className="chat-user-bubble">{msg.content}</div>
                  <div className="chat-user-meta">
                    {msg.timestamp && <span>{msg.timestamp}</span>}
                    <button
                      type="button"
                      className="chat-copy-icon"
                      onClick={() => copyText(msg.id, msg.content)}
                      aria-label="Copier ce message"
                      title="Copier"
                    >
                      {copiedId === msg.id ? (
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : (
                        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                          <rect x="5.5" y="5.5" width="7.5" height="8.5" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
                          <path d="M10.5 5.5V3.5A1.5 1.5 0 0 0 9 2H4.5A1.5 1.5 0 0 0 3 3.5V10a1.5 1.5 0 0 0 1.5 1.5h1" stroke="currentColor" strokeWidth="1.4" />
                        </svg>
                      )}
                    </button>
                  </div>
                </article>
              ) : (
                <article key={msg.id} className="chat-turn-assistant">
                  {msg.intro_text ? (
                    <ProseContent text={msg.intro_text} paragraphClass="chat-assistant-intro" />
                  ) : (
                    msg.running &&
                    msg.tools_used.length === 0 && (
                      <p className="chat-assistant-thinking">Analyse de la demande…</p>
                    )
                  )}

                  <ToolTrace
                    tools={msg.tools_used}
                    totalDurationMs={msg.total_duration_ms}
                    totalCandidates={msg.total_candidates}
                    running={msg.running}
                  />

                  {msg.drafted_message && (
                    <div className="chat-draft-card">
                      <p className="chat-draft-body">{msg.drafted_message}</p>
                      <div className="chat-draft-actions">
                        <button
                          type="button"
                          className="btn ghost app-btn-xs chat-draft-copy"
                          onClick={() => copyText(`draft-${msg.id}`, msg.drafted_message)}
                        >
                          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                            <rect x="5.5" y="5.5" width="7.5" height="8.5" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
                            <path d="M10.5 5.5V3.5A1.5 1.5 0 0 0 9 2H4.5A1.5 1.5 0 0 0 3 3.5V10a1.5 1.5 0 0 0 1.5 1.5h1" stroke="currentColor" strokeWidth="1.4" />
                          </svg>
                          {copiedId === `draft-${msg.id}` ? 'Message copié' : 'Copier le message'}
                        </button>
                      </div>
                    </div>
                  )}

                  {msg.people?.length > 0 && (
                    <>
                      <ContactChainCard
                        people={msg.people}
                        activeUser={activeUser}
                        onSelectPerson={onSelectPerson}
                      />
                      <PeopleTable
                        people={msg.people}
                        onSelectPerson={onSelectPerson}
                        onDraftIntro={handleDraftIntro}
                        disabled={streaming}
                      />
                    </>
                  )}

                  {msg.outro_text && (
                    <ProseContent
                      text={msg.outro_text}
                      paragraphClass={
                        msg.people?.length > 0 ? 'chat-assistant-outro' : 'chat-assistant-intro'
                      }
                    />
                  )}
                </article>
              ),
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && (
        <p className="form-error chat-error" role="alert">
          {error}
        </p>
      )}

      <div className="chat-composer-dock">
        <form
          className="chat-composer"
          onSubmit={(e) => {
            e.preventDefault()
            submitMessage(input)
          }}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              adjustTextareaHeight()
            }}
            onKeyDown={handleKeyDown}
            placeholder="Ex. « Trouve dans les amis de Thomas quelqu’un chez Doctolib » ou « Rédige un message »…"
            aria-label="Message à l’agent réseau"
          />

          <div className="chat-composer-actions">
            {thread.length > 0 && !streaming && (
              <button
                type="button"
                className="chat-reset-btn"
                onClick={handleReset}
                title="Nouvelle conversation"
                aria-label="Nouvelle conversation"
              >
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M3 8a5 5 0 1 0 1.4-3.5L3 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M3 2.5V6h3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}

            {streaming ? (
              <button
                type="button"
                className="chat-send-btn stop"
                onClick={handleAbort}
                aria-label="Arrêter la génération"
                title="Arrêter"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <rect x="3" y="3" width="8" height="8" rx="1.5" fill="currentColor" />
                </svg>
              </button>
            ) : (
              <button
                type="submit"
                className="chat-send-btn"
                disabled={!input.trim()}
                aria-label="Envoyer le message"
                title="Envoyer (Entrée)"
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M8 13V3.5M4 7.5L8 3.5l4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
