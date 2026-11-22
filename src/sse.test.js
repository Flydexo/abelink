import assert from 'node:assert/strict'
import test from 'node:test'
import { readSseStream } from './sse.js'

function responseFrom(text) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({
    start(controller) {
      // Split both SSE delimiters and UTF-8 characters across network chunks.
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte))
      controller.close()
    },
  }))
}

test('chat and action-plan results survive chunked SSE delivery', async () => {
  for (const payload of [{ response: { text: 'Résultats' } }, { data: { response: { text: 'Résultats' } } }]) {
    const events = []
    const response = responseFrom(`event: tool_start\r\ndata: {"id":"search"}\r\n\r\nevent: final_result\r\ndata: ${JSON.stringify(payload)}`)
    assert.deepEqual(await readSseStream(response, (name) => events.push(name)), { text: 'Résultats' })
    assert.deepEqual(events, ['tool_start', 'final_result'])
    assert.equal(response.body.locked, false)
  }
})

test('a server error rejects the search and cancels the stream', async () => {
  let cancelled = false
  const response = new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('event: error\ndata: {"detail":"La recherche a échoué."}\n\n'))
    },
    cancel() { cancelled = true },
  }))
  await assert.rejects(readSseStream(response), /La recherche a échoué/)
  assert.equal(cancelled, true)
  assert.equal(response.body.locked, false)
})

test('a stream ending without results fails instead of leaving a running tool', async () => {
  const response = responseFrom('event: tool_start\ndata: {"id":"search"}\n\n')
  await assert.rejects(readSseStream(response), /interrompue avant de recevoir les résultats/)
  assert.equal(response.body.locked, false)
})

test('a network failure is propagated and releases the stream', async () => {
  const response = new Response(new ReadableStream({
    start(controller) { controller.error(new Error('Connexion perdue')) },
  }))
  await assert.rejects(readSseStream(response), /Connexion perdue/)
  assert.equal(response.body.locked, false)
})
