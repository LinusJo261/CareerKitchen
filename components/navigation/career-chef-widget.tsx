'use client'

import Link from 'next/link'
import { useState } from 'react'
import { Maximize2, MessageCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { ChatPanel } from './chat-panel'
import { ChefAvatar } from './chef-avatar'

export function CareerChefWidget() {
  const [open, setOpen] = useState(false)
  return (
    <Dialog modal={false} open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button type="button" className="chef-launcher group fixed z-40 flex h-14 items-center gap-3 rounded-full border border-butter/35 bg-herb py-1.5 pr-5 pl-1.5 text-flour shadow-[0_8px_30px_-8px_rgba(24,59,50,0.5)] transition-transform hover:-translate-y-1" aria-label="Open Career Chef assistant" title="Get a little help from Career Chef">
          <ChefAvatar className="size-11 transition-transform group-hover:-rotate-6" />
          <span className="text-left"><span className="block font-serif text-lg leading-tight">Career <span className="italic">Chef</span></span><span className="block text-[10px] tracking-wide text-flour/75">A little help, right here</span></span>
          <MessageCircle aria-hidden="true" className="ml-1 size-4 text-butter" />
        </button>
      </DialogTrigger>
      <DialogContent showCloseButton={false} onInteractOutside={event => event.preventDefault()} className="chef-window top-auto left-auto flex w-[calc(100%-1.5rem)] max-w-[410px] translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-2xl border-primary/20 p-0 shadow-[0_16px_70px_-16px_rgba(24,59,50,.35)] sm:max-w-[410px]">
        <DialogTitle className="sr-only">Career Chef assistant</DialogTitle>
        <DialogDescription className="sr-only">Quick guides to onboarding and Career Kitchen, plus optional AI chat. Escape closes this panel.</DialogDescription>
        <ChatPanel compact onNavigate={() => setOpen(false)} actions={<>
          <Button variant="ghost" size="icon" asChild><Link href="/career-chef" onClick={() => setOpen(false)} aria-label="Open full Career Chef page" title="Open full page"><Maximize2 aria-hidden="true" className="size-4" /></Link></Button>
          <DialogClose asChild><Button type="button" variant="ghost" size="icon" aria-label="Close Career Chef"><X aria-hidden="true" className="size-4" /></Button></DialogClose>
        </>} />
      </DialogContent>
    </Dialog>
  )
}
