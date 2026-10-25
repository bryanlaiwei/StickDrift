import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type AssistantAnswer, type ChatTurn } from '../api'

type Message = ChatTurn & { meta?: AssistantAnswer }

export function Assistant({
  residentId,
  name,
  suggestions,
}: {
  residentId?: string
  name?: string
  suggestions: string[]
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const log = useRef<HTMLDivElement>(null)

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  async function ask(question: string) {
    const q = question.trim()
    if (!q || busy) return
    const history: ChatTurn[] = messages.map(({ role, text }) => ({ role, text }))
    setMessages((m) => [...m, { role: 'user', text: q }])
    setInput('')
    setBusy(true)
    setError(null)
    try {
      const res = await api.askAssistant(q, history, residentId)
      setMessages((m) => [...m, { role: 'assistant', text: res.answer, meta: res }])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void ask(input)
  }

  return (
    <section className="panel assistant" aria-label="Care assistant">
      <div className="assistant-head">
        <h2>Care assistant</h2>
        <p className="muted">
          Ask about {name ? `${name}’s` : 'residents’'} results in plain language. Answers use only the recorded
          sessions and never give a diagnosis.
        </p>
      </div>

      <div className="assistant-log" ref={log} aria-live="polite">
        {messages.length === 0 && (
          <div className="assistant-suggest">
            {suggestions.map((s) => (
              <button key={s} type="button" className="chip" onClick={() => void ask(s)} disabled={busy}>
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            <div className="msg-text">{m.text}</div>
            {m.meta && (
              <div className="msg-meta">
                <span className={`source source-${m.meta.source}`}>
                  {m.meta.source === 'gemini' ? 'Gemini · grounded in records' : 'From the records'}
                </span>
                {m.meta.unverified_numbers.length > 0 && (
                  <span className="msg-warn">Check these numbers: {m.meta.unverified_numbers.join(', ')}</span>
                )}
                {m.meta.note && <span className="muted">{m.meta.note}</span>}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-assistant msg-busy">Looking at the records…</div>}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <form className="assistant-form" onSubmit={onSubmit}>
        <label htmlFor={`ask-${residentId ?? 'all'}`} className="sr-only">
          Ask a question
        </label>
        <input
          id={`ask-${residentId ?? 'all'}`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={name ? `e.g. Why was ${name} flagged?` : 'e.g. Who needs a check today?'}
          maxLength={500}
          disabled={busy}
          autoComplete="off"
        />
        <button className="btn" type="submit" disabled={busy || !input.trim()}>
          Ask
        </button>
      </form>
    </section>
  )
}
