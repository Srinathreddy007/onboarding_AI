import { useEffect, useRef, useState } from 'react'
import './App.css'

type MiamiExample = {
  name: string
  neighborhood: string
  description: string
  hours: string
}

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

type ChatResponse = {
  session_id: string
  assistant_message: string
  interests: string[]
  interests_count: number
  examples: MiamiExample[]
  is_complete: boolean
  profile?: { interests: string[] } | null
}

const API = import.meta.env.VITE_API_BASE_URL !== undefined ? import.meta.env.VITE_API_BASE_URL : 'http://127.0.0.1:8000'

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [examples, setExamples] = useState<MiamiExample[]>([])
  const [interestsCount, setInterestsCount] = useState(0)
  const [isComplete, setIsComplete] = useState(false)
  const [profile, setProfile] = useState<ChatResponse['profile']>(null)
  const [error, setError] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const initRef = useRef(false)

  // Clear stale session on fresh load, then request greeting
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    window.localStorage.removeItem('hellocity_session')
    void send('Hi!', false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, examples, loading])

  const send = async (text: string, addToChat: boolean, confirmed?: boolean) => {
    if (!text.trim() && confirmed === undefined) return
    setLoading(true)
    setError(null)
    if (addToChat) {
      setMessages(prev => [...prev, { role: 'user', content: text }])
    }
    try {
      const res = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text, confirmed }),
      })
      if (!res.ok) {
        setError('Something went wrong. Try again.')
        setMessages(prev => [...prev, { role: 'assistant', content: 'Something went wrong. Please try again.' }])
        return
      }
      const data: ChatResponse = await res.json()

      if (!sessionId) {
        window.localStorage.setItem('hellocity_session', data.session_id)
        setSessionId(data.session_id)
      } else if (data.session_id !== sessionId) {
        window.localStorage.setItem('hellocity_session', data.session_id)
        setSessionId(data.session_id)
      }

      setMessages(prev => [...prev, { role: 'assistant', content: data.assistant_message }])
      setExamples(data.examples || [])
      setInterestsCount(data.interests_count)
      setIsComplete(data.is_complete)
      setProfile(data.profile ?? null)
    } catch (err) {
      console.error(err)
      setError('Something went wrong. Try again.')
      setMessages(prev => [...prev, { role: 'assistant', content: 'Something went wrong. Please try again.' }])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading || isComplete) return
    setInput('')
    void send(text, true)
  }

  const handleConfirm = (yes: boolean) => {
    setExamples([])
    void send(yes ? 'Yes, that is what I meant.' : 'No, that is not quite right.', false, yes)
  }

  return (
    <div className="app-root">
      <div className="app-shell">
        {/* Header */}
        <header className="app-header">
          <img src="/hellocity-logo.png" alt="HelloCity" className="logo-img" />
          <div className="header-text">
            <h1>
              <span className="hello">Hello</span>
              <span className="city">City</span>
            </h1>
            <p className="tagline">Miami</p>
          </div>
          <div className="progress">
            {[0, 1, 2].map(i => (
              <div key={i} className={`dot ${i < interestsCount ? 'filled' : ''}`} />
            ))}
          </div>
        </header>

        {/* Chat */}
        <main className="chat-area">
          <div className="chat-scroll">
            {messages.map((m, i) => (
              <div key={i} className={`msg-row ${m.role}`}>
                <div className="msg-bubble">{m.content}</div>
              </div>
            ))}
            {loading && (
              <div className="msg-row assistant">
                <div className="msg-bubble typing">
                  <span /><span /><span />
                </div>
              </div>
            )}

            {/* Example cards */}
            {examples.length > 0 && !isComplete && (
              <div className="examples-block">
                <p className="examples-label">Here are 3 Miami spots:</p>
                <div className="cards">
                  {examples.map(ex => (
                    <div key={ex.name} className="card">
                      <h3>{ex.name}</h3>
                      <span className="card-hood">{ex.neighborhood}</span>
                      <p className="card-desc">{ex.description}</p>
                      <p className="card-hours">{ex.hours}</p>
                    </div>
                  ))}
                </div>
                <div className="confirm-btns">
                  <button className="btn-yes" onClick={() => handleConfirm(true)} disabled={loading}>
                    Yes, that&apos;s what I meant
                  </button>
                  <button className="btn-no" onClick={() => handleConfirm(false)} disabled={loading}>
                    No
                  </button>
                </div>
              </div>
            )}

            {/* Profile */}
            {isComplete && profile && (
              <div className="profile-block">
                <h2>Your Miami Profile</h2>
                <p>Here&apos;s what you&apos;re into:</p>
                <div className="profile-chips">
                  {profile.interests.map(i => (
                    <span key={i} className="profile-chip">{i}</span>
                  ))}
                </div>
                <p className="profile-done">We&apos;ll use this to curate your perfect Miami experience!</p>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        </main>

        {/* Error bar with retry */}
        {error && (
          <div className="error-bar">
            <span>{error}</span>
            <button type="button" className="error-retry" onClick={() => setError(null)}>
              Try again
            </button>
          </div>
        )}

        {/* Input */}
        <form className="input-bar" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder={isComplete ? 'All done!' : 'Type something you enjoy...'}
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={loading || isComplete}
          />
          <button type="submit" className="send-btn" disabled={loading || isComplete || !input.trim()}>
            ➤
          </button>
        </form>
      </div>
    </div>
  )
}

export default App
