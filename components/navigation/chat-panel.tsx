'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useId, useRef } from 'react'
import { ArrowRight, Check, ChevronDown, CircleHelp, CornerDownLeft, KeyRound, LoaderCircle, RotateCcw, Send, ShieldCheck, Sparkles, Unplug } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { chefContext } from '@/lib/career-chef-guide'
import { MAX_MESSAGE_LENGTH } from '@/lib/navigation-chat'
import { useCareerChef } from './career-chef-provider'
import { ChefAvatar } from './chef-avatar'
import { GuidePanel } from './guide-panel'

export function ChatPanel({ compact = false, actions, onNavigate }: { compact?: boolean; actions?: React.ReactNode; onNavigate?: () => void }) {
  const chat = useCareerChef()
  const aiTab = useRef<HTMLButtonElement>(null)
  const guideTab = useRef<HTMLButtonElement>(null)

  function showMode(view: 'guide' | 'ai') {
    chat.setView(view)
    const destination = view === 'ai' ? aiTab : guideTab
    destination.current?.focus()
  }
  return (
    <section className="flex min-h-0 flex-1 flex-col bg-card" aria-label="Career Chef assistant">
      <header className="flex shrink-0 items-center gap-2 border-b px-3 py-3 sm:px-5">
        <ChefAvatar className="size-10 border border-butter/30" />
        <div className="min-w-0 flex-1">
          <h2 className="font-serif text-[22px] leading-none whitespace-nowrap">Career <span className="italic">Chef</span></h2>
          <p className="mt-1 text-[10px] text-muted-foreground">Your kitchen companion</p>
        </div>
        {actions}
      </header>
      <Tabs value={chat.view} onValueChange={value => chat.setView(value === 'ai' ? 'ai' : 'guide')} className="min-h-0 flex-1 gap-0">
        <div className="shrink-0 px-5 pt-3"><TabsList aria-label="Assistant mode" className="w-full"><TabsTrigger ref={guideTab} value="guide">Quick guide</TabsTrigger><TabsTrigger ref={aiTab} value="ai"><Sparkles aria-hidden="true" className="size-3.5" />Ask AI{chat.loading ? <LoaderCircle aria-hidden="true" className="size-3 animate-spin" /> : null}</TabsTrigger></TabsList></div>
        <TabsContent value="guide" className="flex min-h-0 flex-col data-[state=inactive]:hidden"><GuidePanel onNavigate={onNavigate} onAskAI={() => showMode('ai')} /></TabsContent>
        <TabsContent value="ai" className="flex min-h-0 flex-col data-[state=inactive]:hidden"><AIConversation compact={compact} onNavigate={onNavigate} onGuide={() => showMode('guide')} /></TabsContent>
      </Tabs>
    </section>
  )
}

function AIConversation({ compact, onNavigate, onGuide }: { compact: boolean; onNavigate?: () => void; onGuide: () => void }) {
  const chat = useCareerChef()
  const pathname = usePathname()
  const context = chefContext(pathname)
  const id = useId()
  const input = useRef<HTMLTextAreaElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const count = Array.from(chat.draft).length
  const hasConversation = chat.messages.length > 0 || chat.pending !== null
  const needsSession = chat.connection?.authentication === 'session' && !chat.connection.sessionAvailable && !chat.token.trim()
  const starters = [context.question, 'How do mutual introductions work?', 'What information should I share during onboarding?']

  useEffect(() => { void chat.checkConnection() }, [chat.checkConnection, pathname])
  useEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [chat.messages.length, chat.pending, chat.loading, chat.error])

  function chooseStarter(message: string) {
    chat.setDraft(message)
    input.current?.focus()
  }

  return (
    <>
      <div className="flex shrink-0 items-center justify-between gap-2 px-5 pt-3">
        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground"><Sparkles aria-hidden="true" className="size-3" />AI navigation · Google Gemini</span>
        <Button type="button" variant="ghost" size="icon" aria-label="Clear conversation" title="Clear conversation" disabled={!hasConversation && !chat.draft} onClick={() => { chat.reset(); input.current?.focus() }}><RotateCcw aria-hidden="true" className="size-3.5" /></Button>
      </div>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pt-2 pb-5" role="log" aria-label="Chat messages" aria-live="polite" aria-relevant="additions text" tabIndex={0}>
        {!hasConversation ? (
          <div className={cn('mx-auto max-w-lg', !compact && 'py-4')}>
            <h3 className={cn('font-serif leading-tight', compact ? 'text-3xl' : 'text-4xl')}>What’s on<br /><span className="italic text-primary">your mind?</span></h3>
            <p className="mt-3 text-sm text-muted-foreground">Ask about getting started, finding a page, or understanding the next step. I can explain the kitchen; you make the decisions.</p>
            <div className="mt-5 flex flex-col gap-2" aria-label="Suggested questions">
              {starters.map(question => <button key={question} type="button" onClick={() => chooseStarter(question)} className="group flex items-center justify-between gap-3 rounded-lg border bg-background px-3 py-3 text-left text-xs leading-relaxed transition-colors hover:border-primary/40 hover:bg-secondary"><span>{question}</span><ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-primary" /></button>)}
            </div>
            <p className="mt-4 text-[11px] leading-relaxed text-muted-foreground">Chef uses public guidance and cannot view your account, fill in forms, or submit decisions. Chats stay here until you clear or refresh this tab.</p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-5">
            {chat.messages.map(message => (
              <article key={message.id} className={cn('flex flex-col', message.role === 'user' ? 'items-end pl-7' : 'items-start pr-3')}>
                <span className="mb-1.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">{message.role === 'user' ? 'You' : 'Career Chef'}</span>
                <p className={cn('max-w-full whitespace-pre-wrap break-words rounded-xl px-4 py-3 text-sm leading-relaxed [overflow-wrap:anywhere]', message.role === 'user' ? 'rounded-tr-sm bg-primary text-primary-foreground' : 'rounded-tl-sm border bg-background')}>{message.content}</p>
                {message.links?.length ? <div className="mt-2 flex flex-wrap gap-2" aria-label="Suggested pages">{message.links.map(link => <Link key={link.path} href={link.path} onClick={onNavigate} className="inline-flex min-h-10 items-center gap-2 rounded-md border border-primary/25 bg-secondary px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-accent">{link.label}<ArrowRight aria-hidden="true" className="size-3.5" /></Link>)}</div> : null}
              </article>
            ))}
            {chat.pending ? <article className="flex flex-col items-end pl-7"><span className="mb-1.5 font-mono text-[10px] tracking-wider text-muted-foreground uppercase">You</span><p className="max-w-full whitespace-pre-wrap break-words rounded-xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground [overflow-wrap:anywhere]">{chat.pending.message}</p></article> : null}
            {chat.loading ? <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><ChefAvatar className="size-8" /><LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />Preparing a little guidance…</p> : null}
            {chat.error ? <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4"><p className="text-sm">{chat.error}</p><p className="mt-1 text-xs text-muted-foreground">Your question is saved here. Retry checks the same request, or clear the conversation to start again.</p><Button type="button" variant="outline" size="sm" className="mt-3" disabled={!chat.consent || chat.loading} onClick={chat.retry}><RotateCcw aria-hidden="true" className="size-3.5" />Retry question</Button></div> : null}
          </div>
        )}
      </div>
      <div className="min-h-0 max-h-[60%] shrink-0 overflow-y-auto border-t bg-background px-5 pt-3 pb-4">
        {chat.connection && (!chat.connection.apiReachable || needsSession) ? <div className="mb-3 rounded-lg border bg-muted/50 px-3 py-2.5 text-[11px] leading-relaxed"><p>{!chat.connection.apiReachable ? 'AI replies are temporarily unavailable. Quick guides are still here to help.' : 'Sign in to your workspace to ask Career Chef, or connect a session for testing.'}</p><div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">{!chat.connection.apiReachable ? <button type="button" disabled={chat.checking} onClick={() => void chat.checkConnection()} className="min-h-7 rounded-sm font-medium text-primary underline underline-offset-2 disabled:opacity-50">{chat.checking ? 'Checking…' : 'Check again'}</button> : null}{compact && needsSession ? <Link href="/career-chef" onClick={onNavigate} className="inline-flex min-h-7 items-center gap-1 font-medium text-primary underline underline-offset-2">Open session connection<ArrowRight aria-hidden="true" className="size-3" /></Link> : null}<button type="button" onClick={onGuide} className="min-h-7 rounded-sm font-medium text-primary underline underline-offset-2">Use quick guides</button></div></div> : null}
        {!compact ? <details className="group mb-3 text-xs">
          <summary className="flex min-h-8 w-fit cursor-pointer list-none items-center gap-1.5 rounded-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden"><KeyRound aria-hidden="true" className="size-3.5" />Session connection<ChevronDown aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-180" /></summary>
          <div className="mt-2 space-y-3 rounded-lg border bg-card p-3">
            <div className="flex items-start justify-between gap-3"><p className="flex items-start gap-1.5 text-muted-foreground">{chat.connection?.apiReachable ? <Check aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-primary" /> : <CircleHelp aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />}<span>{chat.checking ? 'Checking connection…' : chat.connection ? `${chat.connection.apiReachable ? 'Service reachable' : 'Service unavailable'}. ${chat.connection.sessionAvailable ? 'Your workspace session is connected.' : chat.connection.authentication === 'local' ? 'A local test session is available. This check does not verify AI generation.' : 'Sign in to your workspace or connect a session for testing.'}` : 'Connection status is unavailable. You can still use quick guides.'}</span></p><button type="button" className="min-h-8 shrink-0 rounded-sm text-primary underline underline-offset-2 disabled:opacity-50" disabled={chat.checking} onClick={() => void chat.checkConnection()}>Recheck</button></div>
            <div><label htmlFor={`${id}-token`} className="mb-1 block font-medium">Session access token <span className="font-normal text-muted-foreground">(for connected testing)</span></label><div className="flex gap-1.5"><input id={`${id}-token`} type="password" value={chat.token} onChange={event => chat.setToken(event.target.value)} disabled={chat.loading} autoComplete="off" spellCheck={false} placeholder="Paste your session access token" className="h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-base disabled:opacity-50 sm:text-sm" />{chat.token ? <Button type="button" variant="ghost" size="icon-lg" aria-label="Disconnect session" disabled={chat.loading} onClick={() => { chat.reset(); chat.setToken('') }}><Unplug className="size-4" /></Button> : null}</div><p className="mt-1.5 text-[11px] text-muted-foreground">Held in memory for this tab only. Use a session access token, never a password or an API key.</p></div>
          </div>
        </details> : null}
        <label className="mb-3 flex cursor-pointer items-start gap-2.5 text-[11px] leading-relaxed text-muted-foreground" htmlFor={`${id}-consent`}><input id={`${id}-consent`} type="checkbox" checked={chat.consent} onChange={event => chat.setConsent(event.target.checked)} disabled={chat.loading} className="mt-0.5 size-4 shrink-0 accent-primary" /><span>I agree to send my question and recent chat history to Google Gemini. Please leave out private or sensitive details.</span></label>
        <form onSubmit={event => { event.preventDefault(); if (!needsSession) chat.send() }}>
          <label htmlFor={`${id}-question`} className="sr-only">Your question for Career Chef</label>
          <div className="relative"><Textarea ref={input} id={`${id}-question`} value={chat.draft} onChange={event => chat.setDraft(event.target.value)} disabled={!!chat.pending} rows={2} placeholder={chat.pending ? 'Retry your saved question, or clear to start again.' : 'Ask Chef a question…'} aria-describedby={`${id}-input-help ${id}-input-status`} aria-invalid={count > MAX_MESSAGE_LENGTH} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!needsSession) chat.send() } }} className="min-h-20 max-h-36 resize-none bg-card pr-12 pb-7 text-base sm:text-sm" /><Button type="submit" size="icon" className="absolute right-2 bottom-2" aria-label="Send question" disabled={!chat.consent || !chat.draft.trim() || count > MAX_MESSAGE_LENGTH || !!chat.pending || needsSession}>{chat.loading ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : <Send aria-hidden="true" className="size-4" />}</Button><span aria-hidden="true" className={cn('absolute bottom-2.5 left-3 font-mono text-[10px]', count > MAX_MESSAGE_LENGTH ? 'text-destructive' : 'text-muted-foreground')}>{count} / {MAX_MESSAGE_LENGTH}</span></div>
          <p id={`${id}-input-help`} className="sr-only">Maximum 2000 characters. Enter sends your question. Shift plus Enter adds a new line. Google Gemini consent and a connected session are required.</p>
          <p id={`${id}-input-status`} className={cn('mt-2 text-[10px] leading-relaxed', count > MAX_MESSAGE_LENGTH ? 'text-destructive' : 'text-muted-foreground')} aria-live="polite">{count > MAX_MESSAGE_LENGTH ? `Please remove ${count - MAX_MESSAGE_LENGTH} characters before sending.` : !chat.consent ? 'Choose whether to share with Gemini before sending.' : needsSession ? 'Sign in to send your question.' : chat.loading ? 'Chef is preparing your reply…' : chat.pending ? 'Retry your question, or clear the conversation to start again.' : 'Ready when you are.'}</p>
          <div className="mt-1 flex items-start justify-between gap-3 text-[10px] leading-relaxed text-muted-foreground"><p className="flex items-start gap-1"><ShieldCheck aria-hidden="true" className="mt-0.5 size-3 shrink-0" /><span>AI can make mistakes. Check the suggested pages.</span></p>{!compact ? <span className="hidden shrink-0 items-center gap-1 sm:flex"><CornerDownLeft aria-hidden="true" className="size-3" />Enter to send</span> : null}</div>
        </form>
      </div>
    </>
  )
}
