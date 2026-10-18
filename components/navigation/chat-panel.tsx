'use client'

import Link from 'next/link'
import { useEffect, useId, useRef } from 'react'
import { ArrowRight, Check, ChefHat, ChevronDown, CircleHelp, CornerDownLeft, KeyRound, LoaderCircle, RotateCcw, Send, ShieldCheck, Unplug } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { MAX_MESSAGE_LENGTH } from '@/lib/navigation-chat'
import { useCareerChef } from './career-chef-provider'

const starters = [
  'How do I find my next role?',
  'Where do I post a vacancy?',
  'How do mutual introductions work?',
]

export function ChatPanel({ compact = false, actions, onNavigate }: { compact?: boolean; actions?: React.ReactNode; onNavigate?: () => void }) {
  const chat = useCareerChef()
  const id = useId()
  const input = useRef<HTMLTextAreaElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const count = Array.from(chat.draft).length
  const hasConversation = chat.messages.length > 0 || chat.pending !== null

  useEffect(() => { void chat.checkConnection() }, [chat.checkConnection])
  useEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [chat.messages.length, chat.pending, chat.loading, chat.error])

  function chooseStarter(message: string) {
    chat.setDraft(message)
    input.current?.focus()
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-card" aria-label="Career Chef conversation">
      <header className="flex shrink-0 items-center gap-3 border-b px-5 py-4">
        <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"><ChefHat className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-2xl leading-none">Career <span className="italic">Chef</span></h2>
          <p className="mt-1 font-mono text-[10px] tracking-[.11em] text-muted-foreground uppercase">Your guide to the kitchen</p>
        </div>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Clear conversation" title="Clear conversation" disabled={!hasConversation && !chat.draft} onClick={() => { chat.reset(); input.current?.focus() }}><RotateCcw className="size-4" /></Button>
        {actions}
      </header>

      <div ref={scroller} className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5', compact ? 'min-h-32' : 'min-h-72')} role="log" aria-label="Chat messages" aria-live="polite" aria-relevant="additions text" tabIndex={0}>
        {!hasConversation ? (
          <div className={cn('mx-auto max-w-lg', !compact && 'py-5')}>
            <span className="eyebrow text-paprika-ink">A little direction, freshly served.</span>
            <h3 className={cn('mt-3 font-serif leading-tight', compact ? 'text-3xl' : 'text-4xl')}>What brings you<br /><span className="italic text-primary">to the kitchen?</span></h3>
            <p className="mt-3 max-w-md text-sm text-muted-foreground">I can help you find the right page, understand an introduction, or get started as a candidate or employer.</p>
            <div className="mt-5 flex flex-col gap-2" aria-label="Suggested questions">
              {starters.map(question => (
                <button key={question} type="button" onClick={() => chooseStarter(question)} className="group flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-3 text-left text-sm transition-colors hover:border-primary/40 hover:bg-secondary">
                  <span>{question}</span><ArrowRight aria-hidden="true" className="size-4 shrink-0 text-primary transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-5">
            {chat.messages.map(message => (
              <article key={message.id} className={cn('flex flex-col', message.role === 'user' ? 'items-end pl-7' : 'items-start pr-3')}>
                <span className="mb-1.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">{message.role === 'user' ? 'You' : 'Career Chef'}</span>
                <p className={cn('max-w-full whitespace-pre-wrap break-words rounded-lg px-4 py-3 text-sm leading-relaxed [overflow-wrap:anywhere]', message.role === 'user' ? 'rounded-tr-sm bg-primary text-primary-foreground' : 'rounded-tl-sm border bg-background')}>{message.content}</p>
                {message.links?.length ? (
                  <div className="mt-2 flex flex-wrap gap-2" aria-label="Suggested pages">
                    {message.links.map(link => <Link key={link.path} href={link.path} onClick={onNavigate} className="inline-flex items-center gap-2 rounded-md border border-primary/25 bg-secondary px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-accent">{link.label}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>)}
                  </div>
                ) : null}
              </article>
            ))}
            {chat.pending ? (
              <article className="flex flex-col items-end pl-7">
                <span className="mb-1.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">You</span>
                <p className="max-w-full whitespace-pre-wrap break-words rounded-lg rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground [overflow-wrap:anywhere]">{chat.pending.message}</p>
              </article>
            ) : null}
            {chat.loading ? <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle aria-hidden="true" className="size-4 animate-spin" />Preparing a little guidance…</p> : null}
            {chat.error ? (
              <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
                <p className="text-sm">{chat.error}</p>
                <p className="mt-1 text-xs text-muted-foreground">Your question is saved here. Retry sends the same request.</p>
                <Button type="button" variant="outline" size="sm" className="mt-3" disabled={!chat.consent || chat.loading} onClick={chat.retry}><RotateCcw aria-hidden="true" className="size-3.5" />Retry question</Button>
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t bg-background px-5 pt-3 pb-4">
        <details className="group mb-3 text-xs">
          <summary className="flex w-fit list-none items-center gap-1.5 rounded-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden"><KeyRound aria-hidden="true" className="size-3.5" />Connection details<ChevronDown aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" /></summary>
          <div className="mt-2 space-y-3 rounded-md border bg-card p-3">
            <div className="flex items-start justify-between gap-3">
              <p className="flex items-start gap-1.5 text-muted-foreground">
                {chat.connection?.apiReachable ? <Check aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-primary" /> : <CircleHelp aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />}
                <span>{chat.checking ? 'Checking API connection…' : chat.connection ? `${chat.connection.apiReachable ? 'API connected' : 'API is unreachable'}. ${chat.connection.authentication === 'local' ? 'Local test session is configured on the server.' : 'A valid account access token is required.'}` : 'API status unavailable. Check that the website and API are running.'}</span>
              </p>
              <button type="button" className="shrink-0 rounded-sm text-primary underline underline-offset-2 disabled:opacity-50" disabled={chat.checking} onClick={() => void chat.checkConnection()}>Recheck</button>
            </div>
            <div>
              <label htmlFor={`${id}-token`} className="mb-1 block font-medium">Session access token <span className="font-normal text-muted-foreground">(when required)</span></label>
              <div className="flex gap-1.5">
                <input id={`${id}-token`} type="password" value={chat.token} onChange={event => chat.setToken(event.target.value)} disabled={chat.loading} autoComplete="off" spellCheck={false} placeholder="Paste your access token" className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-sm disabled:opacity-50" />
                {chat.token ? <Button type="button" variant="ghost" size="icon" aria-label="Disconnect session" disabled={chat.loading} onClick={() => chat.setToken('')}><Unplug className="size-4" /></Button> : null}
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">Held in memory for this tab. Your Gemini API key belongs in the server environment.</p>
            </div>
          </div>
        </details>

        <label className="mb-3 flex cursor-pointer items-start gap-2.5 text-[11px] leading-relaxed text-muted-foreground" htmlFor={`${id}-consent`}>
          <input id={`${id}-consent`} type="checkbox" checked={chat.consent} onChange={event => chat.setConsent(event.target.checked)} disabled={chat.loading} className="mt-0.5 size-4 shrink-0 accent-primary" />
          <span>I agree to send my question and recent chat history to Google Gemini for navigation help. Please leave out private or sensitive details.</span>
        </label>
        <form onSubmit={event => { event.preventDefault(); chat.send() }}>
          <label htmlFor={`${id}-question`} className="sr-only">Your question for Career Chef</label>
          <div className="relative">
            <Textarea ref={input} id={`${id}-question`} value={chat.draft} onChange={event => chat.setDraft(event.target.value)} disabled={!!chat.pending} rows={2} placeholder={chat.pending ? 'Retry your saved question or clear the conversation.' : 'Ask your way around…'} aria-describedby={`${id}-input-help`} aria-invalid={count > MAX_MESSAGE_LENGTH} onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); chat.send() }
            }} className="min-h-20 max-h-36 resize-none bg-card pr-12 pb-7 text-sm" />
            <Button type="submit" size="icon-sm" className="absolute right-2 bottom-2" aria-label="Send question" disabled={!chat.consent || !chat.draft.trim() || count > MAX_MESSAGE_LENGTH || !!chat.pending}>{chat.loading ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : <Send aria-hidden="true" className="size-4" />}</Button>
            <span aria-hidden="true" className={cn('absolute bottom-2.5 left-3 font-mono text-[10px]', count > MAX_MESSAGE_LENGTH ? 'text-destructive' : 'text-muted-foreground')}>{count} / {MAX_MESSAGE_LENGTH}</span>
          </div>
          <p id={`${id}-input-help`} className="sr-only">Maximum 2000 characters. Enter sends your question. Shift plus Enter adds a new line. Google Gemini consent is required.</p>
          <div className="mt-2 flex items-start justify-between gap-3 text-[10px] leading-relaxed text-muted-foreground">
            <p className="flex items-start gap-1"><ShieldCheck aria-hidden="true" className="mt-0.5 size-3 shrink-0" /><span>AI guidance can be mistaken. Check suggested pages.</span></p>
            {!compact ? <span className="hidden shrink-0 items-center gap-1 sm:flex"><CornerDownLeft aria-hidden="true" className="size-3" />Enter to send</span> : null}
          </div>
        </form>
      </div>
    </section>
  )
}
