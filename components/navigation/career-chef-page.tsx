'use client'

import Link from 'next/link'
import { ArrowLeft, ArrowUpRight, Compass, LockKeyhole, Sparkles } from 'lucide-react'
import { Brand } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { ChatPanel } from './chat-panel'
import { ChefAvatar } from './chef-avatar'

export function CareerChefPage() {
  return (
    <div className="min-h-dvh">
      <a href="#chef-main" className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:bg-card focus:px-3 focus:py-2">Skip to Career Chef</a>
      <header className="page-width flex h-20 items-center justify-between gap-4 border-b">
        <Brand />
        <Button variant="ghost" size="sm" asChild><Link href="/"><ArrowLeft aria-hidden="true" className="size-4" /><span className="hidden sm:inline">Back to the kitchen</span><span className="sm:hidden">Home</span></Link></Button>
      </header>
      <main id="chef-main" className="page-width grid gap-7 py-7 lg:grid-cols-[minmax(0,.75fr)_minmax(0,1.25fr)] lg:gap-14 lg:py-12">
        <div className="lg:pt-5">
          <div className="flex items-center gap-3"><span className="eyebrow text-paprika-ink">At your service</span><span aria-hidden="true" className="h-px max-w-24 flex-1 bg-border" /></div>
          <ChefAvatar className="mt-5 hidden size-24 -rotate-6 border border-butter/30 bg-accent/40 lg:flex" />
          <h1 className="mt-5 font-serif text-4xl leading-[1.05] tracking-tight sm:text-6xl">Find your way.<br /><span className="italic text-primary">Pull up a chair.</span></h1>
          <p className="mt-4 max-w-md text-sm text-muted-foreground sm:text-base">Meet Career Chef, your guide to Career Kitchen. Start with a quick onboarding guide, or choose Ask AI for help with a question.</p>
          <div className="mt-8 hidden space-y-5 lg:block">
            <div className="flex items-start gap-3"><Compass aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">A guide around the kitchen</p><p className="mt-1 text-sm text-muted-foreground">Find candidate profiles, opportunities, employer vacancies, and the pages in between.</p></div></div>
            <div className="flex items-start gap-3"><LockKeyhole aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">You stay in control</p><p className="mt-1 text-sm text-muted-foreground">Chef uses the public guide. It cannot view your account, send messages, or make decisions for you. Refreshing the page clears this chat.</p></div></div>
            <div className="flex items-start gap-3"><Sparkles aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">Quick guides, plus optional AI</p><p className="mt-1 text-sm text-muted-foreground">Quick guides work without a connection. AI replies use Google Gemini and need a connected session and your consent before sending.</p></div></div>
          </div>
          <div className="mt-8 hidden border-t pt-5 lg:block">
            <p className="eyebrow">Know where you are headed?</p>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-3 text-sm text-primary">
              <Link href="/candidate/opportunities" className="inline-flex items-center gap-1 hover:underline">Opportunities<ArrowUpRight aria-hidden="true" className="size-3.5" /></Link>
              <Link href="/employer/vacancies" className="inline-flex items-center gap-1 hover:underline">Vacancies<ArrowUpRight aria-hidden="true" className="size-3.5" /></Link>
              <Link href="/get-started" className="inline-flex items-center gap-1 hover:underline">Get started<ArrowUpRight aria-hidden="true" className="size-3.5" /></Link>
            </div>
          </div>
        </div>
        <div className="flex h-[min(780px,calc(100dvh-7rem))] min-h-[570px] flex-col overflow-hidden rounded-2xl border border-primary/20 shadow-[0_14px_45px_-25px_rgba(40,37,33,.3)]"><ChatPanel /></div>
      </main>
      <footer className="page-width pb-8"><p className="font-mono text-[10px] leading-relaxed tracking-wide text-muted-foreground">Demo workspace pages use fictional data. Chef provides navigation guidance; it does not confirm account activity.</p></footer>
    </div>
  )
}
