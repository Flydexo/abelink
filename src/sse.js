export async function readSseStream(res, onEvent) {
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
    if (eventName === 'error') {
      throw new Error(typeof parsed?.detail === 'string' ? parsed.detail : 'La recherche a échoué. Veuillez réessayer.')
    }
    onEvent?.(eventName, parsed)
    if (eventName === 'final_result') {
      if (parsed?.data?.response) {
        finalResponse = parsed.data.response
      } else if (parsed?.response) {
        finalResponse = parsed.response
      }
    }
  }

  let completed = false
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) {
        completed = true
        buffer += decoder.decode()
        break
      }
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) {
        if (frame.trim()) dispatchFrame(frame)
      }
    }
    if (buffer.trim()) dispatchFrame(buffer)
    if (!finalResponse) throw new Error('La recherche a été interrompue avant de recevoir les résultats. Veuillez réessayer.')
    return finalResponse
  } finally {
    if (!completed) await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
