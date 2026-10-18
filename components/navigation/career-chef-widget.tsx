'use client'

import Link from 'next/link'
import { useState } from 'react'
import { ChefHat, Maximize2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ChatPanel } from './chat-panel'

export function CareerChefWidget() {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button type="button" className="fixed right-4 bottom-4 z-40 flex h-12 items-center gap-2.5 rounded-full border border-butter/40 bg-herb px-4 text-flour shadow-[0_6px_24px_-8px_rgba(24,59,50,0.55)] transition-transform hover:-translate-y-0.5 md:right-6 md:bottom-6" aria-label="Open Career Chef navigation assistant">
          <ChefHat aria-hidden="true" className="size-5" /><span className="font-serif text-lg">Ask <span className="italic">Chef</span></span><span aria-hidden="true" className="size-1.5 rounded-full bg-butter" />
        </button>
      </DialogTrigger>
      <DialogContent showCloseButton={false} className="top-auto right-4 bottom-4 left-auto flex h-[min(740px,calc(100dvh-2rem))] w-[calc(100%-2rem)] max-w-[430px] translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden p-0 sm:max-w-[430px] md:right-6 md:bottom-6">
        <DialogTitle className="sr-only">Career Chef navigation assistant</DialogTitle>
        <DialogDescription className="sr-only">Ask for help finding your way around Career Kitchen. You choose whether to send your questions to Google Gemini.</DialogDescription>
        <ChatPanel compact onNavigate={() => setOpen(false)} actions={<>
          <Button variant="ghost" size="icon-sm" asChild><Link href="/career-chef" onClick={() => setOpen(false)} aria-label="Open full Career Chef page" title="Open full page"><Maximize2 aria-hidden="true" className="size-4" /></Link></Button>
          <DialogClose asChild><Button type="button" variant="ghost" size="icon-sm" aria-label="Close Career Chef"><X aria-hidden="true" className="size-4" /></Button></DialogClose>
        </>} />
      </DialogContent>
    </Dialog>
  )
}
