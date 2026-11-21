const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

function buildHeaders(userId, extra = {}) {
  const headers = { ...extra }
  if (userId) {
    headers['X-Profile-Id'] = userId
    headers['X-Demo-User-Id'] = userId
  }
  return headers
}

async function parseError(response) {
  let detail = `Erreur HTTP ${response.status}`
  try {
    const data = await response.json()
    if (data?.detail) {
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    }
  } catch {
    // Ignore non-JSON error payloads
  }
  throw new Error(detail)
}

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`)
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function fetchMe(userId) {
  const res = await fetch(`${API_BASE}/api/v1/me`, {
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function searchDirectory(query = '', limit = 15, userId = null) {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  const res = await fetch(`${API_BASE}/api/v1/profiles?${params.toString()}`, {
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function fetchProfile(profileId, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/profiles/${encodeURIComponent(profileId)}`, {
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function fetchGraphPath(targetId, userId = null, maxHops = 4, kPaths = 3) {
  const params = new URLSearchParams({
    target_id: targetId,
    max_hops: String(maxHops),
    k_paths: String(kPaths),
  })
  if (userId) params.set('source_id', userId)
  const res = await fetch(`${API_BASE}/api/v1/graph/path?${params.toString()}`, {
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

async function readSseStream(res, onEvent) {
  if (!res.body) throw new Error('Flux SSE indisponible sur ce navigateur.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let finalResponse = null

  const dispatchFrame = (rawFrame) => {
    const lines = rawFrame.split(/\r?\n/)
    let eventName = 'message'
    const dataLines = []
    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
    }
    if (!dataLines.length) return
    const parsed = JSON.parse(dataLines.join('\n'))
    onEvent?.(eventName, parsed)
    if (eventName === 'final_result') {
      if (parsed?.data?.response) {
        finalResponse = parsed.data.response
      } else if (parsed?.response) {
        finalResponse = parsed.response
      }
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      if (frame.trim()) dispatchFrame(frame)
    }
  }
  if (buffer.trim()) dispatchFrame(buffer)
  return finalResponse
}

export async function streamActionPlan(payload, userId, onEvent, signal) {
  const res = await fetch(`${API_BASE}/api/v1/search/action-plan/stream`, {
    method: 'POST',
    headers: buildHeaders(userId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ ...payload, user_id: userId || payload.user_id || null }),
    signal,
  })
  if (!res.ok) await parseError(res)
  return readSseStream(res, onEvent)
}

export async function sendChat(messages, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: 'POST',
    headers: buildHeaders(userId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ messages, user_id: userId || null }),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function streamChat(messages, userId, onEvent, signal) {
  const res = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: 'POST',
    headers: buildHeaders(userId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ messages, user_id: userId || null }),
    signal,
  })
  if (!res.ok) await parseError(res)
  return readSseStream(res, onEvent)
}

export async function draftOutreachMessage(payload, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/search/draft-message`, {
    method: 'POST',
    headers: buildHeaders(userId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ ...payload, user_id: userId || payload.user_id || null }),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function importLinkedInArchive(formData, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/linkedin/import`, {
    method: 'POST',
    headers: buildHeaders(userId),
    body: formData,
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function importLinkCSDump(file, importToken) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('confirmed', 'true')
  const res = await fetch(`${API_BASE}/api/v1/linkcs/import`, {
    method: 'POST',
    headers: importToken ? { 'X-LinkCS-Import-Token': importToken } : {},
    body: formData,
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function importAbelinkBundle(file, importToken, onProgress) {
  const endpoint = `${API_BASE}/api/v1/linkcs/bundle`
  const headers = { 'X-LinkCS-Import-Token': importToken }
  async function send(url, options) {
    const response = await fetch(url, { ...options, headers: { ...headers, ...options?.headers } })
    if (!response.ok) await parseError(response)
    return response.status === 204 ? null : response.json()
  }

  const { id, chunk_size: chunkSize } = await send(`${endpoint}?size=${file.size}&confirmed=true`, { method: 'POST' })
  const upload = `${endpoint}/${id}`
  try {
    for (let offset = 0; offset < file.size;) {
      const chunk = file.slice(offset, offset + chunkSize)
      const { received } = await send(`${upload}?offset=${offset}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: chunk,
      })
      offset = received
      onProgress(offset)
    }
    await send(`${upload}/finish`, { method: 'POST' })
  } catch (error) {
    await send(upload, { method: 'DELETE' }).catch(() => {})
    throw error
  }

  for (;;) {
    const result = await send(upload)
    if (result.state === 'completed') return { ...result.summary, warning: result.warning }
    if (result.state === 'failed') throw new Error(result.detail)
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }
}

export async function listApiTokens(userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/tokens`, {
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function createApiToken(label, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/tokens`, {
    method: 'POST',
    headers: buildHeaders(userId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ label }),
  })
  if (!res.ok) await parseError(res)
  return res.json()
}

export async function revokeApiToken(tokenId, userId = null) {
  const res = await fetch(`${API_BASE}/api/v1/tokens/${encodeURIComponent(tokenId)}`, {
    method: 'DELETE',
    headers: buildHeaders(userId),
  })
  if (!res.ok) await parseError(res)
  return true
}
