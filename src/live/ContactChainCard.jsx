import ProfileAvatar from './ProfileAvatar.jsx'

function firstName(fullName, fallback = 'Contact') {
  const parts = String(fullName || '').trim().split(/\s+/)
  return parts[0] || fallback
}

function ChainArrow() {
  return (
    <span className="contact-chain-arrow" aria-hidden="true">
      <svg width="18" height="14" viewBox="0 0 18 14" fill="none">
        <path
          d="M1 7h15M11.5 2.5 16 7l-4.5 4.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  )
}

export default function ContactChainCard({ people = [], activeUser, onSelectPerson }) {
  if (!people.length) return null

  const target = people[0]
  const relay = target.mutuals?.[0] || null
  const targetFirst = firstName(target.full_name)
  const relayFirst = relay ? firstName(relay.full_name) : null

  return (
    <section className="contact-chain-card" aria-label="Chaîne de contact suggérée">
      <div className="contact-chain-top">
        <span className="contact-chain-eyebrow">Qui contacter</span>
        <div className="contact-chain-channels">
          <span className="contact-chain-pill">
            {relay ? `Via ${relayFirst}` : 'Contact direct'}
          </span>
          <span className="contact-chain-pill is-accent">
            {relay ? 'LinkedIn' : 'LinkedIn / Email'}
          </span>
        </div>
      </div>

      <p className="contact-chain-hint">
        {relay ? (
          <>
            Demandez une mise en relation à <strong>{relayFirst}</strong> sur LinkedIn pour
            joindre <strong>{targetFirst}</strong>.
          </>
        ) : (
          <>
            Contactez <strong>{targetFirst}</strong> directement par message LinkedIn ou email.
          </>
        )}
      </p>

      <div className="contact-chain-flow">
        <div className="contact-chain-node is-self">
          <span className="contact-chain-avatar">
            <ProfileAvatar
              src={activeUser?.photo_url}
              name={activeUser?.full_name || 'Vous'}
            />
          </span>
          <span className="contact-chain-meta">
            <span className="contact-chain-name">Vous</span>
            <span className="contact-chain-role">Départ</span>
          </span>
        </div>

        <ChainArrow />

        {relay && (
          <>
            <button
              type="button"
              className="contact-chain-node is-interactive"
              onClick={() => relay.id && onSelectPerson?.(relay.id)}
              title={`Voir le profil de ${relayFirst}`}
            >
              <span className="contact-chain-avatar">
                <ProfileAvatar src={relay.photo_url} name={relay.full_name} />
              </span>
              <span className="contact-chain-meta">
                <span className="contact-chain-name">{relayFirst}</span>
                <span className="contact-chain-role">Relais</span>
              </span>
            </button>
            <ChainArrow />
          </>
        )}

        <button
          type="button"
          className="contact-chain-node is-target is-interactive"
          onClick={() => target.id && onSelectPerson?.(target.id)}
          title={`Voir le profil de ${targetFirst}`}
        >
          <span className="contact-chain-avatar">
            <ProfileAvatar src={target.photo_url} name={target.full_name} />
          </span>
          <span className="contact-chain-meta">
            <span className="contact-chain-name">{targetFirst}</span>
            <span className="contact-chain-role">
              {target.role_company || 'Personne visée'}
            </span>
          </span>
        </button>
      </div>
    </section>
  )
}
