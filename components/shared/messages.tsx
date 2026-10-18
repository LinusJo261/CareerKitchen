'use client'
import { useState } from 'react'
import { ArrowLeft, MessageSquare, SendHorizontal } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Message, MessageContent } from '@/components/ui/message'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import {
  MessageScroller,
  MessageScrollerProvider,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { EmptyNote, Initials, PageHeader } from '@/components/workspace/kit'
import { useWorkspace } from '@/lib/workspace'
import type { Role } from '@/lib/contracts'
import { cn } from '@/lib/utils'

export function MessagesPage({ role }: { role: Role }) {
  const { data, execute } = useWorkspace()
  const threads = data.conversations.filter((c) => c.side === role)
  const [activeId, setActiveId] = useState<string | null>(
    threads[0]?.id ?? null,
  )
  const [mobileOpen, setMobileOpen] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const active = threads.find((t) => t.id === activeId) ?? threads[0]
  const [sending, setSending] = useState(false)
  const draft = active ? (drafts[active.id] ?? '') : ''

  async function send() {
    const original = draft
    const text = draft.trim()
    if (!text || !active || sending) return
    setSending(true)
    try {
      const ok = await execute('message.send', {
        matchId: active.matchId,
        body: text,
        expected_version: active.version,
      })
      if (ok)
        setDrafts((current) =>
          current[active.id] === original
            ? { ...current, [active.id]: '' }
            : current,
        )
    } finally {
      setSending(false)
    }
  }

  if (threads.length === 0)
    return (
      <>
        <PageHeader eyebrow="Conversations" title="Messages" />
        <EmptyNote
          icon={MessageSquare}
          title="No conversations yet"
          description="Conversations open once interest is mutual. Nobody can message you before that."
        />
      </>
    )

  return (
    <>
      <PageHeader
        eyebrow="Conversations"
        title="Messages"
        description="Conversations only open after mutual interest — so every thread here is with someone who wants to talk."
      />
      <div className="panel grid h-[calc(100dvh-20rem)] min-h-[480px] overflow-hidden md:grid-cols-[280px_minmax(0,1fr)]">
        <nav
          aria-label="Conversations"
          className={cn(
            'flex flex-col border-r',
            mobileOpen && 'hidden md:flex',
          )}
        >
          {threads.map((t) => (
            <button
              key={t.id}
              onClick={() => {
                setActiveId(t.id)
                setMobileOpen(true)
              }}
              className={cn(
                'flex items-center gap-3 border-b p-4 text-left transition-colors hover:bg-muted',
                t.id === active?.id && 'bg-secondary',
              )}
              aria-current={t.id === active?.id ? 'true' : undefined}
            >
              <Initials name={t.name} />
              <span className="min-w-0 flex-1">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{t.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {t.messages.at(-1)?.time}
                  </span>
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {t.messages.at(-1)?.text}
                </span>
              </span>
            </button>
          ))}
        </nav>
        {active && (
          <section
            className={cn(
              'flex min-h-0 flex-col',
              !mobileOpen && 'hidden md:flex',
            )}
            aria-label={`Conversation with ${active.name}`}
          >
            <header className="flex items-center gap-3 border-b px-5 py-4">
              <Button
                variant="ghost"
                size="icon-sm"
                className="md:hidden"
                onClick={() => setMobileOpen(false)}
                aria-label="Back to conversations"
              >
                <ArrowLeft />
              </Button>
              <Initials name={active.name} className="size-9" />
              <div>
                <p className="text-sm font-medium">{active.name}</p>
                <p className="text-xs text-muted-foreground">
                  {active.role} · {active.company}
                </p>
              </div>
            </header>
            <MessageScrollerProvider
              key={active.id}
              defaultScrollPosition="end"
            >
              <MessageScroller className="flex-1">
                <MessageScrollerViewport className="px-5 py-6">
                  <MessageScrollerContent className="gap-4">
                    {active.messages.length === 0 && (
                      <p className="text-center text-sm text-muted-foreground">
                        Interest is mutual. Send a message to start the
                        conversation.
                      </p>
                    )}
                    {active.messages.map((m) => (
                      <MessageScrollerItem key={m.id}>
                        <Message align={m.mine ? 'end' : 'start'}>
                          <MessageContent>
                            <Bubble variant={m.mine ? 'default' : 'muted'}>
                              <BubbleContent className="whitespace-pre-wrap">
                                {m.text}
                              </BubbleContent>
                            </Bubble>
                            <span className="text-[11px] text-muted-foreground">
                              {m.time}
                            </span>
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    ))}
                  </MessageScrollerContent>
                </MessageScrollerViewport>
                <MessageScrollerButton />
              </MessageScroller>
            </MessageScrollerProvider>
            <form
              className="flex items-end gap-2 border-t p-4"
              onSubmit={(e) => {
                e.preventDefault()
                send()
              }}
            >
              <Textarea
                aria-label="Write a message"
                placeholder={`Message ${active.name.split(' ')[0]}…`}
                rows={1}
                maxLength={5000}
                disabled={sending}
                className="min-h-10 resize-none"
                value={draft}
                onChange={(e) =>
                  setDrafts((current) => ({
                    ...current,
                    [active.id]: e.target.value,
                  }))
                }
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    if (e.nativeEvent.isComposing || e.keyCode === 229) return
                    e.preventDefault()
                    send()
                  }
                }}
              />
              <Button
                type="submit"
                size="icon"
                aria-label={sending ? 'Sending message' : 'Send message'}
                disabled={!draft.trim() || sending}
              >
                <SendHorizontal />
              </Button>
            </form>
          </section>
        )}
      </div>
    </>
  )
}
