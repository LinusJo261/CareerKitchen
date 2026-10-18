'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, BriefcaseBusiness, Building2, Handshake, ShieldCheck, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { chefContext, chefGuides, type ChefGuideId } from '@/lib/career-chef-guide'
import { ChefAvatar } from './chef-avatar'

const guideIcons = { candidate: BriefcaseBusiness, employer: Building2, introductions: Handshake, privacy: ShieldCheck }

export function GuidePanel({ onNavigate, onAskAI }: { onNavigate?: () => void; onAskAI: () => void }) {
  const context = chefContext(usePathname())
  const [selected, setSelected] = useState<ChefGuideId | null>(null)
  const title = useRef<HTMLHeadingElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const guideButtons = useRef<Partial<Record<ChefGuideId, HTMLButtonElement | null>>>({})
  const returnFocus = useRef<ChefGuideId | null>(null)
  const guide = chefGuides.find(item => item.id === selected)
  const orderedGuides = [...chefGuides].sort((a, b) => Number(b.id === context.guide) - Number(a.id === context.guide))

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = 0
    if (selected) title.current?.focus({ preventScroll: true })
    else if (returnFocus.current) {
      guideButtons.current[returnFocus.current]?.focus()
      returnFocus.current = null
    }
  }, [selected])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
        {guide ? (
          <div className="mx-auto max-w-lg">
            <button type="button" onClick={() => { returnFocus.current = selected; setSelected(null) }} className="mb-5 inline-flex min-h-9 items-center gap-2 rounded-sm text-xs font-medium text-primary hover:underline"><ArrowLeft aria-hidden="true" className="size-3.5" />All quick guides</button>
            <p className="eyebrow text-paprika-ink">A recipe for your next step</p>
            <h3 ref={title} tabIndex={-1} className="mt-2 rounded-sm font-serif text-3xl leading-tight focus:outline-none">{guide.title}</h3>
            <p className="mt-3 text-sm text-muted-foreground">{guide.introduction}</p>
            <ol className="mt-6 space-y-6">
              {guide.steps.map((step, index) => (
                <li key={step.title} className="flex gap-3">
                  <span aria-hidden="true" className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-primary/20 bg-secondary font-mono text-[10px] text-primary">0{index + 1}</span>
                  <div className="min-w-0"><h4 className="text-sm font-medium">{step.title}</h4><p className="mt-1 text-sm text-muted-foreground">{step.text}</p>{'path' in step ? <Link href={step.path} onClick={onNavigate} className="mt-2 inline-flex min-h-9 items-center gap-1.5 rounded-sm text-xs font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary">{step.label}<ArrowRight aria-hidden="true" className="size-3.5" /></Link> : null}</div>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <div className="mx-auto max-w-lg">
            <div className="flex items-start justify-between gap-3">
              <div className="pt-2"><p className="eyebrow text-paprika-ink">{context.label}</p><h3 className="mt-3 font-serif text-3xl leading-[1.08]">A little guidance,<br /><span className="italic text-primary">freshly served.</span></h3></div>
              <ChefAvatar className="hidden size-16 -rotate-6 border border-butter/30 bg-accent/40 min-[360px]:inline-flex sm:size-20" />
            </div>
            <p className="mt-4 text-sm text-muted-foreground">Hi, I’m Chef. Let’s find your next step. Pick a quick guide, or ask me a question with AI.</p>
            <div className="mt-5 space-y-2" aria-label="Quick guides">
              {orderedGuides.map(item => {
                const Icon = guideIcons[item.id]
                return <button key={item.id} ref={element => { guideButtons.current[item.id] = element }} type="button" onClick={() => setSelected(item.id)} className="group flex w-full items-center gap-3 rounded-xl border bg-background px-3.5 py-3.5 text-left transition-colors hover:border-primary/35 hover:bg-secondary"><span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary"><Icon aria-hidden="true" className="size-4" /></span><span className="min-w-0 flex-1"><span className="block text-sm font-medium">{item.title}</span><span className="mt-0.5 block text-[11px] leading-relaxed text-muted-foreground">{item.description}</span></span><ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-primary transition-transform group-hover:translate-x-0.5" /></button>
              })}
            </div>
          </div>
        )}
      </div>
      <footer className="shrink-0 border-t bg-background px-5 py-4">
        <Button type="button" variant="secondary" className="h-10 w-full" onClick={onAskAI}><Sparkles aria-hidden="true" className="size-4" />Ask Chef with AI<ArrowRight aria-hidden="true" className="ml-auto size-4" /></Button>
        <p className="mt-2 text-center text-[10px] leading-relaxed text-muted-foreground">Quick guides are written guidance. No AI request is sent.</p>
      </footer>
    </div>
  )
}
