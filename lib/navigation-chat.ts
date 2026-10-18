/** The browser only sends completed turns; drafts and failed requests stay local. */
export type NavigationTurn = { role: 'user' | 'assistant'; content: string }
export type NavigationLink = { label: string; path: string }
export type NavigationMessage = NavigationTurn & { id: string; links?: NavigationLink[] }
export type NavigationReply = { reply: string; links: NavigationLink[]; version: 1 }

export const MAX_MESSAGE_LENGTH = 2000

const destinations = new Set([
  '/get-started', '/candidate/profile', '/candidate/opportunities', '/candidate/matches',
  '/candidate/messages', '/candidate/offers', '/candidate/privacy', '/candidate/evidence',
  '/candidate/interviews', '/employer/vacancies', '/employer/team', '/employer/messages',
  '/employer/offers',
])

/** Keep whole pairs, newest first in importance, within the API context budget. */
export function navigationHistory(messages: NavigationTurn[], message: string): NavigationTurn[] {
  const history: NavigationTurn[] = []
  let length = Array.from(message).length
  for (let index = messages.length - 2; index >= 0 && history.length < 10; index -= 2) {
    const user = messages[index]
    const assistant = messages[index + 1]
    if (user.role !== 'user' || assistant.role !== 'assistant') break
    const pairLength = Array.from(user.content).length + Array.from(assistant.content).length
    if (length + pairLength > 12000) break
    history.unshift({ role: 'user', content: user.content }, { role: 'assistant', content: assistant.content })
    length += pairLength
  }
  return history
}

export function parseNavigationReply(value: unknown): NavigationReply | null {
  if (!value || typeof value !== 'object' || !('data' in value)) return null
  const data = value.data
  if (!data || typeof data !== 'object' || !('reply' in data) || !('links' in data) || !('version' in data)) return null
  if (data.version !== 1 || typeof data.reply !== 'string' || !data.reply.trim() || Array.from(data.reply).length > 4000 || !Array.isArray(data.links) || data.links.length > 3) return null
  const links: NavigationLink[] = []
  for (const link of data.links) {
    if (!link || typeof link !== 'object' || typeof link.label !== 'string' || !link.label.trim() || link.label.length > 200 || typeof link.path !== 'string' || !destinations.has(link.path)) return null
    links.push({ label: link.label, path: link.path })
  }
  return { reply: data.reply, links, version: 1 }
}

export function navigationError(value: unknown, status: number): string {
  if (value && typeof value === 'object' && 'error' in value) {
    const error = value.error
    if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string' && error.message.length <= 500) return error.message
  }
  if (status === 401 || status === 403) return 'Connect a valid session in Connection details to use Career Chef.'
  if (status === 429) return 'The kitchen is busy. Wait a moment, then retry your question.'
  if (status === 503) return 'Career Chef is unavailable. Check the API connection and server-side Gemini configuration.'
  return 'Your question could not be completed. Please retry.'
}
