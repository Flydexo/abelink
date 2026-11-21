import { useEffect, useRef, useState } from 'react'
import ProfileAvatar from './ProfileAvatar.jsx'

export default function PeopleTable({
  people = [],
  onSelectPerson,
  onDraftIntro,
  disabled = false,
}) {
  const [openMutualKey, setOpenMutualKey] = useState(null) // `${personId}:${mutualId}`
  const tableRef = useRef(null)

  useEffect(() => {
    if (!openMutualKey) return
    const onDocMouseDown = (e) => {
      if (tableRef.current && !tableRef.current.contains(e.target)) {
        setOpenMutualKey(null)
      }
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpenMutualKey(null)
    }
    addEventListener('mousedown', onDocMouseDown)
    addEventListener('keydown', onKeyDown)
    return () => {
      removeEventListener('mousedown', onDocMouseDown)
      removeEventListener('keydown', onKeyDown)
    }
  }, [openMutualKey])

  if (!people.length) return null

  return (
    <div className="people-table-wrap" ref={tableRef}>
      <table className="people-table">
        <thead>
          <tr>
            <th scope="col">Personne</th>
            <th scope="col">Analyse</th>
            <th scope="col" className="col-mutuals">Contacts communs</th>
          </tr>
        </thead>
        <tbody>
          {people.map((person) => {
            const mutuals = person.mutuals || []
            const visibleMutuals = mutuals.slice(0, 3)
            const extraCount = mutuals.length - visibleMutuals.length

            return (
              <tr key={person.id}>
                <td className="cell-person">
                  <div className="person-cell-inner">
                    <button
                      type="button"
                      className="person-avatar"
                      onClick={() => onSelectPerson?.(person.id)}
                      title={`Voir la fiche de ${person.full_name}`}
                    >
                      <ProfileAvatar src={person.photo_url} name={person.full_name} />
                    </button>
                    <div className="person-identity">
                      <button
                        type="button"
                        className="person-name-btn"
                        onClick={() => onSelectPerson?.(person.id)}
                      >
                        {person.full_name}
                      </button>
                      <span className="person-role">
                        {person.role_company || 'Alumni CentraleSupélec'}
                      </span>
                      {person.location && (
                        <span className="person-location">
                          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                            <path
                              d="M8 14.2s4.5-4.1 4.5-7.7a4.5 4.5 0 1 0-9 0c0 3.6 4.5 7.7 4.5 7.7Z"
                              stroke="currentColor"
                              strokeWidth="1.4"
                              strokeLinejoin="round"
                            />
                            <circle cx="8" cy="6.5" r="1.5" stroke="currentColor" strokeWidth="1.3" />
                          </svg>
                          <span>{person.location}</span>
                        </span>
                      )}
                    </div>
                  </div>
                </td>

                <td className="cell-thinking">
                  <p className="thinking-text">
                    {person.thinking}
                    {person.source_url && (
                      <>
                        {person.thinking ? ' ' : ''}
                        <a
                          href={person.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="source-chip"
                        >
                          <span>
                            {person.source_label ||
                              (person.source_url.includes('linkedin.com') ? 'LinkedIn' : 'Profil')}
                          </span>
                          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                            <path d="M3.5 8.5L8.5 3.5M4.5 3.5h4v4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </a>
                      </>
                    )}
                  </p>
                </td>

                <td className="cell-mutuals">
                  {mutuals.length > 0 ? (
                    <div className="mutuals-cell-inner">
                      <div className="mutuals-stack">
                        {visibleMutuals.map((mutual) => {
                          const key = `${person.id}:${mutual.id}`
                          const isOpen = openMutualKey === key
                          return (
                            <div key={mutual.id} className="mutual-anchor">
                              <button
                                type="button"
                                className={`mutual-avatar-btn${isOpen ? ' active' : ''}`}
                                onClick={() => setOpenMutualKey(isOpen ? null : key)}
                                aria-expanded={isOpen}
                                title={`${mutual.full_name} — Voir le lien`}
                              >
                                <ProfileAvatar src={mutual.photo_url} name={mutual.full_name} />
                              </button>

                              {isOpen && (
                                <div className="mutual-popover" role="dialog" aria-label={`Contact commun : ${mutual.full_name}`}>
                                  <div className="mutual-popover-head">
                                    <div>
                                      <button
                                        type="button"
                                        className="mutual-popover-name"
                                        onClick={() => {
                                          setOpenMutualKey(null)
                                          onSelectPerson?.(mutual.id)
                                        }}
                                      >
                                        {mutual.full_name}
                                      </button>
                                      {mutual.short_meta && (
                                        <p className="mutual-popover-meta">{mutual.short_meta}</p>
                                      )}
                                    </div>
                                    {mutual.probability > 0 && (
                                      <span className="mutual-prob-pill">
                                        {Math.round(mutual.probability * 100)} %
                                      </span>
                                    )}
                                  </div>

                                  {mutual.reason && (
                                    <p className="mutual-popover-reason">{mutual.reason}</p>
                                  )}

                                  <button
                                    type="button"
                                    className="btn primary app-btn-xs mutual-draft-btn"
                                    disabled={disabled}
                                    onClick={() => {
                                      setOpenMutualKey(null)
                                      onDraftIntro?.(person, mutual)
                                    }}
                                  >
                                    Rédiger un message
                                  </button>
                                </div>
                              )}
                            </div>
                          )
                        })}
                        {extraCount > 0 && (
                          <span className="mutual-extra-badge">+{extraCount}</span>
                        )}
                      </div>
                    </div>
                  ) : person.hop_count === 1 ? (
                    <div className="mutuals-cell-inner">
                      <button
                        type="button"
                        className="direct-chip-btn"
                        disabled={disabled}
                        onClick={() => onDraftIntro?.(person, null)}
                        title={`Rédiger un message direct à ${person.full_name}`}
                      >
                        Direct
                      </button>
                    </div>
                  ) : (
                    <span className="muted small">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
