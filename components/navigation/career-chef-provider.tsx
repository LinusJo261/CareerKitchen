'use client'

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { usePathname } from 'next/navigation'
import { CareerChefWidget } from './career-chef-widget'
import { MAX_MESSAGE_LENGTH, navigationError, navigationHistory, parseNavigationReply, type NavigationMessage } from '@/lib/navigation-chat'

type PendingQuestion = { id: string; message: string; body: string }
type Connection = { authentication: 'local' | 'session'; apiReachable: boolean } | null

function useCareerChefState() {
  const [messages, setMessages] = useState<NavigationMessage[]>([])
  const [draft, setDraft] = useState('')
  const [consent, setConsent] = useState(false)
  const [token, setToken] = useState('')
  const [pending, setPending] = useState<PendingQuestion | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState<Connection>(null)
  const [checking, setChecking] = useState(false)
  const activeRequest = useRef<AbortController | null>(null)
  const checkingRequest = useRef<AbortController | null>(null)

  useEffect(() => () => {
    const active = activeRequest.current
    const checking = checkingRequest.current
    activeRequest.current = null
    checkingRequest.current = null
    active?.abort()
    checking?.abort()
  }, [])

  const checkConnection = useCallback(async () => {
    if (checkingRequest.current) return
    const controller = new AbortController()
    checkingRequest.current = controller
    setChecking(true)
    try {
      const response = await fetch('/api/navigation/chat', { cache: 'no-store', signal: controller.signal })
      const result: unknown = await response.json()
      if (response.ok && result && typeof result === 'object' && 'data' in result && result.data && typeof result.data === 'object' && 'authentication' in result.data && 'api_reachable' in result.data && (result.data.authentication === 'local' || result.data.authentication === 'session') && typeof result.data.api_reachable === 'boolean') {
        setConnection({ authentication: result.data.authentication, apiReachable: result.data.api_reachable })
      } else setConnection(null)
    } catch {
      if (!controller.signal.aborted) setConnection(null)
    } finally {
      if (checkingRequest.current === controller) {
        checkingRequest.current = null
        setChecking(false)
      }
    }
  }, [])

  async function request(question: PendingQuestion) {
    if (activeRequest.current || !consent) return
    const controller = new AbortController()
    activeRequest.current = controller
    setLoading(true)
    setError(null)
    const timeout = window.setTimeout(() => controller.abort('timeout'), 65000)
    try {
      const response = await fetch('/api/navigation/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': question.id,
          ...(token.trim() ? { Authorization: `Bearer ${token.trim()}` } : {}),
        },
        body: question.body,
        signal: controller.signal,
      })
      const result: unknown = await response.json().catch(() => null)
      if (!response.ok) throw new Error(navigationError(result, response.status))
      const reply = parseNavigationReply(result)
      if (!reply) throw new Error('Career Chef returned an unreadable reply. Please retry your question.')
      if (activeRequest.current !== controller) return
      setMessages(previous => [...previous, { id: `${question.id}-user`, role: 'user', content: question.message }, { id: `${question.id}-assistant`, role: 'assistant', content: reply.reply, links: reply.links }])
      setPending(null)
    } catch (cause) {
      if (activeRequest.current !== controller) return
      setError(controller.signal.aborted ? 'The reply took too long. Retry to check the same request.' : cause instanceof Error ? cause.message : 'The connection was interrupted. Please retry your question.')
    } finally {
      window.clearTimeout(timeout)
      if (activeRequest.current === controller) {
        activeRequest.current = null
        setLoading(false)
      }
    }
  }

  function send(message = draft) {
    const trimmed = message.trim()
    if (!trimmed || Array.from(trimmed).length > MAX_MESSAGE_LENGTH || !consent || pending || activeRequest.current) return
    const question = {
      id: crypto.randomUUID(),
      message: trimmed,
      body: JSON.stringify({ message: trimmed, consent_to_gemini: true, history: navigationHistory(messages, trimmed) }),
    }
    setPending(question)
    setDraft('')
    void request(question)
  }

  function reset() {
    const controller = activeRequest.current
    activeRequest.current = null
    controller?.abort()
    setMessages([])
    setPending(null)
    setDraft('')
    setError(null)
    setLoading(false)
  }

  return { messages, draft, setDraft, consent, setConsent, token, setToken, pending, loading, error, connection, checking, checkConnection, send, retry: () => { if (pending) void request(pending) }, reset }
}

type CareerChefState = ReturnType<typeof useCareerChefState>
const CareerChefContext = createContext<CareerChefState | null>(null)

export function useCareerChef() {
  const state = useContext(CareerChefContext)
  if (!state) throw new Error('Career Chef needs its provider.')
  return state
}

export function CareerChefProvider({ children }: { children: React.ReactNode }) {
  const state = useCareerChefState()
  const pathname = usePathname()
  return (
    <CareerChefContext.Provider value={state}>
      {children}
      {pathname !== '/career-chef' ? <CareerChefWidget /> : null}
    </CareerChefContext.Provider>
  )
}
