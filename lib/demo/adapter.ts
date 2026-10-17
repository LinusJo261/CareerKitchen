'use client'
// Isolated in-memory demo adapter. Replace with an HTTP adapter that calls the
// FastAPI backend; server responses then become authoritative.
import useSWR from 'swr'
import { toast } from 'sonner'
import { initialState } from './fixtures'
import { ApiError, type DemoState, type FrontendAdapter } from '../contracts'

let state: DemoState = structuredClone(initialState)

export const demoAdapter: FrontendAdapter = {
  async getState() {
    return structuredClone(state)
  },
  async update(updater, expectedRevision) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) throw new ApiError('offline', 'You appear to be offline. Your change was not saved.')
    if (expectedRevision !== state.revision) throw new ApiError('conflict', 'This view changed. Please review it and try again.')
    const next = updater(structuredClone(state))
    state = { ...next, revision: state.revision + 1 }
    return structuredClone(state)
  },
  async reset() {
    state = structuredClone(initialState)
    return structuredClone(state)
  },
}

export function useDemo() {
  const { data = initialState, error, mutate, isLoading } = useSWR<DemoState>('career-kitchen-demo', () => demoAdapter.getState(), {
    fallbackData: initialState,
    revalidateOnFocus: false,
  })
  async function update(updater: (state: DemoState) => DemoState, message?: string) {
    try {
      await mutate(await demoAdapter.update(updater, data.revision), { revalidate: false })
      if (message) toast.success(message)
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Unable to update. Try again.')
      await mutate()
      return false
    }
  }
  async function reset() {
    await mutate(await demoAdapter.reset(), { revalidate: false })
    toast.success('Demo data restored to its original state.')
  }
  return { data, error, isLoading, update, reset }
}
