import { useState } from 'react'

function formatDuration(ms) {
  if (!ms || ms < 1000) return '< 1s'
  return `${Math.round(ms / 1000)}s`
}

function formatToolDuration(ms) {
  if (!ms || ms < 1000) return ''
  return `${(ms / 1000).toFixed(1).replace(/\.0$/, '')}s`
}

export default function ToolTrace({
  tools = [],
  totalDurationMs = 0,
  totalCandidates = 0,
  running = false,
}) {
  const [expanded, setExpanded] = useState(true)

  if (!running && tools.length === 0) return null

  const doneCount = tools.filter((t) => t.status === 'done').length
  const failed = tools.some((t) => t.status === 'error')
  const cancelled = tools.some((t) => t.status === 'cancelled')
  const totalTools = tools.length
  const headerText = running
    ? 'Exécution des outils…'
    : failed ? 'La recherche a échoué'
    : cancelled ? 'Recherche interrompue'
    : `${totalTools} outil${totalTools > 1 ? 's' : ''} exécuté${totalTools > 1 ? 's' : ''} en ${formatDuration(totalDurationMs)}`

  return (
    <div className="chat-trace">
      <button
        type="button"
        className="chat-trace-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {running ? (
          <span className="chat-trace-spinner" aria-hidden="true" />
        ) : (
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="7" cy="7" r="4.8" stroke="currentColor" strokeWidth="1.5" />
            <path d="M10.8 10.8L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        )}
        <span>{headerText}</span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          className={`chat-trace-chevron${expanded ? ' open' : ''}`}
          aria-hidden="true"
        >
          <path d="M4 10l4-4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {expanded && (
        <div className="chat-trace-body">
          <ul className="chat-trace-list">
            {tools.map((tool) => {
              const isRunning = tool.status === 'running'
              const toolDuration = !isRunning ? formatToolDuration(tool.duration_ms) : ''
              const detailText = typeof tool.detail === 'string' ? tool.detail.trim() : ''
              return (
                <li key={tool.id} className={`chat-trace-item${isRunning ? ' running' : ''}`}>
                  <span className={isRunning ? 'chat-trace-node-spin' : 'chat-trace-node'} aria-hidden="true" />
                  <div className="chat-trace-content">
                    <div className="chat-trace-row">
                      <span className="chat-trace-label">{tool.label}</span>
                      {!isRunning && tool.count !== null && tool.count !== undefined && (
                        <span className="chat-trace-count">{tool.count}</span>
                      )}
                      {toolDuration && (
                        <span className="chat-trace-duration">{toolDuration}</span>
                      )}
                    </div>
                    {detailText && <p className="chat-trace-detail">{detailText}</p>}
                  </div>
                </li>
              )
            })}
          </ul>

          {!running && doneCount > 0 && totalCandidates > 0 && (
            <div className="chat-trace-footer">
              <svg className="chat-trace-elbow" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <path d="M4 0v8a3 3 0 0 0 3 3h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                <path d="M11 8.5L13.5 11 11 13.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="chat-trace-pill">
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <circle cx="6" cy="5.5" r="2.3" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M2 13c0-2.1 1.8-3.5 4-3.5s4 1.4 4 3.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                  <circle cx="11.5" cy="6.2" r="1.7" stroke="currentColor" strokeWidth="1.3" />
                  <path d="M11.2 9.8c1.6.2 2.8 1.4 2.8 3.2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                </svg>
                <span>Profils</span>
                <strong>{totalCandidates}</strong>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
