import { useEffect, useState } from 'react'

export function getInitials(name = '') {
  return name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

export default function ProfileAvatar({ src, name = '', fallback }) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
  }, [src])

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name ? `Photo de ${name}` : ''}
        referrerPolicy="no-referrer"
        className="profile-avatar-img"
        onError={() => setFailed(true)}
      />
    )
  }

  return fallback ?? getInitials(name)
}
