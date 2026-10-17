'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import { Bell, ChevronDown, Menu, Moon, Sun, ArrowLeftRight } from 'lucide-react'
import { Brand } from '@/components/brand'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useDemo } from '@/lib/demo/adapter'
import { usePass, arrange } from '@/lib/demo/pass'
import { cn } from '@/lib/utils'
import type { Role } from '@/lib/contracts'

interface Station { path: string; name: string; action: string; also?: string[] }

const stations: Record<Role, Station[]> = {
  candidate: [
    { path: '', name: 'Today’s Menu', action: 'Review opportunities', also: ['opportunities'] },
    { path: 'matches', name: 'The Table', action: 'Your introductions' },
    { path: 'evidence', name: 'Taste Tests', action: 'Questions & evidence' },
    { path: 'profile', name: 'Mise en Place', action: 'Profile & preferences' },
    { path: 'history', name: 'Recipe Book', action: 'Your history' },
  ],
  employer: [
    { path: 'vacancies', name: 'Open Orders', action: 'Your positions' },
    { path: 'pass', name: 'The Pass', action: 'Review candidates', also: ['candidates', ''] },
    { path: 'taste-tests', name: 'Taste Tests', action: 'Verification requests' },
    { path: 'pipeline', name: 'The Table', action: 'Introductions' },
    { path: 'history', name: 'Recipe Book', action: 'Order history' },
  ],
}

const backOffice: Record<Role, [string, string][]> = {
  candidate: [['messages', 'Messages'], ['interviews', 'Interviews'], ['offers', 'Offers'], ['privacy', 'Privacy & consent'], ['notifications', 'Notifications'], ['settings', 'Settings']],
  employer: [['messages', 'Messages'], ['interviews', 'Interviews'], ['offers', 'Offers'], ['organization', 'Organization'], ['pact', 'Agreements · PACT'], ['witness', 'Hiring clarity · WITNESS'], ['team', 'Team & permissions'], ['notifications', 'Notifications'], ['settings', 'Settings']],
}

const href = (role: Role, path: string) => `/${role}${path ? `/${path}` : ''}`

export function Shell({ role, children }: { role: Role; children: React.ReactNode }) {
  const pathname = usePathname()
  const { theme, setTheme } = useTheme()
  const { data } = useDemo()
  const pass = usePass()
  const employer = role === 'employer'
  const isActive = (s: Station) => [s.path, ...(s.also ?? [])].some((p) => pathname === href(role, p))
  const counts: Record<string, number> = employer
    ? { pass: arrange(pass).onPass.filter((e) => !pass.introductions[e.candidate.id]).length, 'taste-tests': pass.tasteTests.filter((t) => t.status === 'Awaiting reply').length }
    : { '': data.opportunities.filter((o) => o.status === 'Active' && !data.decisions[o.id]).length }
  const unread = data.notifications.some((n) => !n.read && n.side === role)

  const stationLinks = (vertical: boolean) =>
    stations[role].map((s) => {
      const active = isActive(s)
      const count = counts[s.path]
      return (
        <Link
          key={s.path}
          href={href(role, s.path)}
          aria-current={active ? 'page' : undefined}
          className={cn(
            'group relative flex flex-col justify-center transition-colors',
            vertical ? 'border-b px-6 py-4' : 'h-full px-4 xl:px-5',
            employer && !vertical ? 'text-flour/65 hover:text-flour' : 'text-muted-foreground hover:text-foreground',
            active && (employer && !vertical ? 'text-flour' : 'text-foreground'),
          )}
        >
          <span className="flex items-center gap-2 font-serif text-[17px] leading-tight whitespace-nowrap">
            {s.name}
            {count > 0 && (
              <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-[2px] bg-paprika px-1 font-mono text-[10px] leading-none text-charcoal">
                {count}
                <span className="sr-only"> waiting</span>
              </span>
            )}
          </span>
          <span className="font-mono text-[10px] tracking-[0.12em] whitespace-nowrap uppercase opacity-80">{s.action}</span>
          {active && !vertical && <span aria-hidden="true" className={cn('absolute inset-x-4 bottom-0 h-[3px] xl:inset-x-5', employer ? 'bg-butter' : 'bg-paprika')} />}
          {active && vertical && <span aria-hidden="true" className="absolute inset-y-3 left-0 w-[3px] bg-paprika" />}
        </Link>
      )
    })

  return (
    <div className="flex min-h-screen flex-col">
      <header className={cn('sticky top-0 z-40 border-b', employer ? 'border-herb bg-herb text-flour' : 'bg-background/95 backdrop-blur-sm')}>
        <div className="flex h-[68px] items-stretch gap-2 px-4 md:px-6">
          <div className="flex items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className={cn('lg:hidden', employer && 'text-flour hover:bg-flour/10 hover:text-flour')} aria-label="Open kitchen navigation">
                  <Menu />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-80 p-0">
                <SheetTitle className="sr-only">Kitchen navigation</SheetTitle>
                <div className="border-b px-6 py-5"><Brand /></div>
                <nav aria-label="Stations" className="flex flex-col">{stationLinks(true)}</nav>
                <p className="eyebrow px-6 pt-6 pb-2">Back office</p>
                <nav aria-label="Back office" className="flex flex-col px-3 pb-6">
                  {backOffice[role].map(([p, l]) => (
                    <Link key={p} href={href(role, p)} className="rounded-sm px-3 py-2 text-sm text-muted-foreground hover:bg-muted hover:text-foreground">{l}</Link>
                  ))}
                </nav>
              </SheetContent>
            </Sheet>
            <span className={cn(employer && '[&_.ticket]:bg-butter [&_.ticket]:text-charcoal')}><Brand /></span>
            <span className={cn('hidden border-l pl-3 font-mono text-[10px] tracking-[0.14em] uppercase md:block', employer ? 'border-flour/20 text-flour/70' : 'text-muted-foreground')}>
              {employer ? <>Kitchen<br />{data.organization.name}</> : <>Dining<br />Alex Morgan</>}
            </span>
          </div>

          <nav aria-label="Stations" className="ml-4 hidden flex-1 items-stretch lg:flex">{stationLinks(false)}</nav>

          <div className="ml-auto flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className={cn('font-mono text-[11px] tracking-[0.12em] uppercase', employer && 'text-flour hover:bg-flour/10 hover:text-flour')}>
                  Back office <ChevronDown data-icon="inline-end" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-60">
                <DropdownMenuLabel className="eyebrow">Back office</DropdownMenuLabel>
                <DropdownMenuGroup>
                  {backOffice[role].map(([p, l]) => (
                    <DropdownMenuItem key={p} asChild><Link href={href(role, p)}>{l}</Link></DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem asChild>
                    <Link href={employer ? '/candidate' : '/employer/pass'}><ArrowLeftRight />Switch to {employer ? 'candidate' : 'employer'} demo</Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
                    {theme === 'dark' ? <Sun /> : <Moon />}{theme === 'dark' ? 'Day service' : 'Night service'}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="ghost" size="icon" asChild className={cn('relative', employer && 'text-flour hover:bg-flour/10 hover:text-flour')}>
              <Link href={href(role, 'notifications')} aria-label={unread ? 'Notifications, unread' : 'Notifications'}>
                <Bell />
                {unread && <span aria-hidden="true" className="absolute top-2 right-2 size-1.5 rounded-full bg-paprika" />}
              </Link>
            </Button>
          </div>
        </div>
      </header>
      <p className="flex items-center justify-center gap-2 border-b bg-accent px-4 py-1.5 text-center font-mono text-[10px] tracking-[0.12em] text-accent-foreground uppercase">
        Demo service · Every person, company and record is fictional · Changes reset on refresh
      </p>
      <main className={cn('mx-auto w-full flex-1 p-5 md:p-8', employer ? 'max-w-[1500px]' : 'max-w-[1240px] md:py-12')}>{children}</main>
      <footer className="double-rule mx-5 flex flex-wrap justify-between gap-2 py-5 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase md:mx-8">
        <span>Career Kitchen · {employer ? 'Kitchen' : 'Dining room'}</span>
        <span>A few introductions, made with care</span>
      </footer>
    </div>
  )
}
