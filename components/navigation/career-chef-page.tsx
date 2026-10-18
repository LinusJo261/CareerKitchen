'use client'

import Link from 'next/link'
import { ArrowLeft, ArrowUpRight, Compass, LockKeyhole, Sparkles } from 'lucide-react'
import { Brand } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { ChatPanel } from './chat-panel'

export function CareerChefPage() {
  return (
    <div className="min-h-dvh">
      <header className="page-width flex h-20 items-center justify-between gap-4 border-b">
        <Brand />
        <Button variant="ghost" size="sm" asChild><Link href="/"><ArrowLeft aria-hidden="true" className="size-4" /><span className="hidden sm:inline">Back to the kitchen</span><span className="sm:hidden">Home</span></Link></Button>
      </header>
      <main className="page-width grid gap-8 py-8 lg:grid-cols-[minmax(0,.75fr)_minmax(0,1.25fr)] lg:gap-14 lg:py-12">
        <div className="lg:pt-5">
          <div className="flex items-center gap-3"><span className="eyebrow text-paprika-ink">At your service</span><span aria-hidden="true" className="h-px max-w-24 flex-1 bg-border" /></div>
          <h1 className="mt-5 font-serif text-5xl leading-[1.05] tracking-tight sm:text-6xl">Find your way.<br /><span className="italic text-primary">Pull up a chair.</span></h1>
          <p className="mt-5 max-w-md text-base text-muted-foreground">Meet Career Chef, your AI guide to Career Kitchen. Tell us what you are looking for, and we will help you find the next step.</p>
          <div className="mt-8 hidden space-y-5 lg:block">
            <div className="flex items-start gap-3"><Compass aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">A guide around the kitchen</p><p className="mt-1 text-sm text-muted-foreground">Find candidate profiles, opportunities, employer vacancies, and the pages in between.</p></div></div>
            <div className="flex items-start gap-3"><LockKeyhole aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">You stay in control</p><p className="mt-1 text-sm text-muted-foreground">Chef uses the public guide. It cannot view your account, send messages, or make decisions for you. Refreshing the page clears this chat.</p></div></div>
            <div className="flex items-start gap-3"><Sparkles aria-hidden="true" className="mt-1 size-4 shrink-0 text-primary" /><div><p className="text-sm font-medium">Powered by Google Gemini</p><p className="mt-1 text-sm text-muted-foreground">Questions and recent conversation are sent to Google only when you consent and send.</p></div></div>
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
        <div className="flex h-[min(800px,calc(100dvh-7rem))] min-h-[620px] flex-col overflow-hidden rounded-lg border shadow-[0_14px_45px_-25px_rgba(40,37,33,.3)]"><ChatPanel /></div>
      </main>
      <footer className="page-width pb-8"><p className="font-mono text-[10px] leading-relaxed tracking-wide text-muted-foreground">Demo workspace pages use fictional data. Chef provides navigation guidance; it does not confirm account activity.</p></footer>
    </div>
  )
}
