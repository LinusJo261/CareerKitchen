'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTheme } from 'next-themes'
import {
  Bell,
  ChevronDown,
  Menu,
  Moon,
  Sun,
  ArrowLeftRight,
  Ellipsis,
  LoaderCircle,
} from 'lucide-react'
import { Brand } from '@/components/brand'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useWorkspace } from '@/lib/workspace'
import { cn } from '@/lib/utils'
import type { Role } from '@/lib/contracts'

interface Station {
  path: string
  name: string
  action: string
  also?: string[]
}

const stations: Record<Role, Station[]> = {
  candidate: [
    {
      path: 'opportunities',
      name: 'Today’s Menu',
      action: 'Review opportunities',
      also: [''],
    },
    { path: 'matches', name: 'The Table', action: 'Your introductions' },
    { path: 'evidence', name: 'Taste Tests', action: 'Questions & evidence' },
    { path: 'profile', name: 'Mise en Place', action: 'Profile & preferences' },
  ],
  employer: [
    { path: 'vacancies', name: 'Open Orders', action: 'Your positions' },
    {
      path: 'pass',
      name: 'The Pass',
      action: 'Review candidates',
      also: ['candidates', ''],
    },
    { path: 'pipeline', name: 'The Table', action: 'Introductions' },
  ],
}

const backOffice: Record<Role, [string, string][]> = {
  candidate: [
    ['messages', 'Messages'],
    ['interviews', 'Interviews'],
    ['offers', 'Offers'],
    ['privacy', 'Privacy & consent'],
    ['notifications', 'Notifications'],
    ['settings', 'Settings'],
  ],
  employer: [
    ['messages', 'Messages'],
    ['interviews', 'Interviews'],
    ['offers', 'Offers'],
    ['organization', 'Organization'],
    ['pact', 'Agreements · PACT'],
    ['witness', 'Hiring clarity · WITNESS'],
    ['team', 'Team & permissions'],
    ['notifications', 'Notifications'],
    ['settings', 'Settings'],
  ],
}

const href = (role: Role, path: string) => `/${role}${path ? `/${path}` : ''}`

export function Shell({
  role,
  children,
}: {
  role: Role
  children: React.ReactNode
}) {
  const pathname = usePathname()
  const { resolvedTheme, setTheme } = useTheme()
  const { data, error, isLoading, refresh } = useWorkspace()
  const employer = role === 'employer'
  const isActive = (s: Station) =>
    [s.path, ...(s.also ?? [])].some((p) => pathname === href(role, p))
  const counts: Record<string, number> = employer
    ? {
        pass: data.candidates.filter(
          (candidate) => !data.candidateDecisions[candidate.id],
        ).length,
      }
    : {
        opportunities: Math.min(
          data.profile.capacity,
          data.opportunities.filter(
            (o) => o.status === 'Active' && !data.decisions[o.id],
          ).length,
        ),
      }
  const unread = data.notifications.some((n) => !n.read && n.side === role)

  if (isLoading && !data.session)
    return (
      <div
        className="flex min-h-screen flex-col items-center justify-center gap-4 p-6"
        role="status"
      >
        <Brand />
        <LoaderCircle className="size-6 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">Loading your workspace…</p>
      </div>
    )

  if (error || !data.session)
    return (
      <main className="mx-auto flex min-h-screen max-w-xl flex-col items-start justify-center gap-5 p-6">
        <Brand />
        <h1 className="text-2xl">Your workspace is unavailable</h1>
        <p className="text-sm text-muted-foreground" role="alert">
          {error instanceof Error
            ? error.message
            : 'Sign in to load your account and saved workspace.'}
        </p>
        <div className="flex gap-3">
          <Button asChild>
            <Link href={`/sign-in?role=${role}`}>Sign in</Link>
          </Button>
          <Button variant="outline" onClick={() => refresh()}>
            Try again
          </Button>
        </div>
      </main>
    )

  const stationLinks = (vertical: boolean) =>
    stations[role].map((s) => {
      const active = isActive(s)
      const count = counts[s.path]
      const link = (
        <Link
          key={s.path}
          href={href(role, s.path)}
          aria-current={active ? 'page' : undefined}
          className={cn(
            'group relative flex flex-col justify-center transition-colors',
            vertical ? 'border-b px-6 py-4' : 'h-full px-4 xl:px-5',
            employer && !vertical
              ? 'text-flour/65 hover:text-flour'
              : 'text-muted-foreground hover:text-foreground',
            active &&
              (employer && !vertical ? 'text-flour' : 'text-foreground'),
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
          <span className="font-mono text-[10px] tracking-[0.12em] whitespace-nowrap uppercase opacity-80">
            {s.action}
          </span>
          {active && !vertical && (
            <span
              aria-hidden="true"
              className={cn(
                'absolute inset-x-4 bottom-0 h-[3px] xl:inset-x-5',
                employer ? 'bg-butter' : 'bg-paprika',
              )}
            />
          )}
          {active && vertical && (
            <span
              aria-hidden="true"
              className="absolute inset-y-3 left-0 w-[3px] bg-paprika"
            />
          )}
        </Link>
      )
      return vertical ? (
        <SheetClose key={s.path} asChild>
          {link}
        </SheetClose>
      ) : (
        link
      )
    })

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#workspace-main"
        className="sr-only z-[70] rounded-md bg-primary px-4 py-3 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to main content
      </a>
      <header
        className={cn(
          'sticky top-0 z-40 border-b',
          employer
            ? 'border-herb bg-herb text-flour'
            : 'bg-background/95 backdrop-blur-sm',
        )}
      >
        <div className="flex h-[68px] items-stretch gap-2 px-4 md:px-6">
          <div className="flex items-center gap-3">
            <Sheet>
              <SheetTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn(
                    'size-10 xl:hidden',
                    employer && 'text-flour hover:bg-flour/10 hover:text-flour',
                  )}
                  aria-label="Open kitchen navigation"
                >
                  <Menu />
                </Button>
              </SheetTrigger>
              <SheetContent
                side="left"
                className="w-80 max-w-[calc(100vw-2rem)] gap-0 overflow-y-auto p-0"
              >
                <SheetTitle className="sr-only">Kitchen navigation</SheetTitle>
                <SheetDescription className="sr-only">
                  Choose a station or manage your workspace.
                </SheetDescription>
                <div className="border-b px-6 py-5">
                  <Brand />
                </div>
                <nav aria-label="Stations" className="flex flex-col">
                  {stationLinks(true)}
                </nav>
                <p className="eyebrow px-6 pt-6 pb-2">Back office</p>
                <nav
                  aria-label="Back office"
                  className="flex flex-col px-3 pb-6"
                >
                  {backOffice[role].map(([p, l]) => (
                    <SheetClose key={p} asChild>
                      <Link
                        href={href(role, p)}
                        aria-current={
                          pathname === href(role, p) ? 'page' : undefined
                        }
                        className={cn(
                          'rounded-sm px-3 py-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground',
                          pathname === href(role, p) &&
                            'bg-muted text-foreground',
                        )}
                      >
                        {l}
                      </Link>
                    </SheetClose>
                  ))}
                </nav>
              </SheetContent>
            </Sheet>
            <span
              className={cn(
                employer && '[&_.ticket]:bg-butter [&_.ticket]:text-charcoal',
              )}
            >
              <Brand className="hidden sm:flex" />
              <Brand compact className="sm:hidden" />
            </span>
            <span
              className={cn(
                'hidden max-w-36 truncate border-l pl-3 font-mono text-[10px] tracking-[0.14em] uppercase 2xl:block',
                employer
                  ? 'border-flour/20 text-flour/70'
                  : 'text-muted-foreground',
              )}
            >
              {employer ? (
                <>
                  Kitchen
                  <br />
                  {data.organization.name}
                </>
              ) : (
                <>
                  Dining
                  <br />
                  {data.profile.name || data.session.email}
                </>
              )}
            </span>
          </div>

          <nav
            aria-label="Stations"
            className="ml-4 hidden flex-1 items-stretch xl:flex"
          >
            {stationLinks(false)}
          </nav>

          <div className="ml-auto flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Open workspace menu"
                  className={cn(
                    'h-10 font-mono text-[11px] tracking-[0.12em] uppercase',
                    employer && 'text-flour hover:bg-flour/10 hover:text-flour',
                  )}
                >
                  <span className="hidden sm:inline">Back office</span>
                  <ChevronDown
                    className="hidden sm:block"
                    data-icon="inline-end"
                  />
                  <Ellipsis className="sm:hidden" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-60">
                <DropdownMenuLabel className="eyebrow">
                  Back office
                </DropdownMenuLabel>
                <DropdownMenuGroup>
                  {backOffice[role].map(([p, l]) => (
                    <DropdownMenuItem key={p} asChild>
                      <Link
                        href={href(role, p)}
                        aria-current={
                          pathname === href(role, p) ? 'page' : undefined
                        }
                      >
                        {l}
                      </Link>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                  <DropdownMenuItem asChild>
                    <Link href={employer ? '/candidate' : '/employer/pass'}>
                      <ArrowLeftRight />
                      {employer ? 'Candidate workspace' : 'Employer workspace'}
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() =>
                      setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')
                    }
                  >
                    {resolvedTheme === 'dark' ? <Sun /> : <Moon />}
                    {resolvedTheme === 'dark' ? 'Day service' : 'Night service'}
                  </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon"
              asChild
              className={cn(
                'relative size-10',
                employer && 'text-flour hover:bg-flour/10 hover:text-flour',
              )}
            >
              <Link
                href={href(role, 'notifications')}
                aria-label={unread ? 'Notifications, unread' : 'Notifications'}
              >
                <Bell />
                {unread && (
                  <span
                    aria-hidden="true"
                    className="absolute top-2 right-2 size-1.5 rounded-full bg-paprika"
                  />
                )}
              </Link>
            </Button>
          </div>
        </div>
      </header>
      <p className="flex items-center justify-center gap-2 border-b bg-accent px-4 py-1.5 text-center font-mono text-[10px] tracking-[0.12em] text-accent-foreground uppercase">
        {data.context.mode === 'local'
          ? 'Local development service · Account data is stored by the backend'
          : 'Connected workspace · Changes are saved to your account'}
      </p>
      {data.warnings.length > 0 && (
        <div
          className="border-b bg-muted px-5 py-3 text-sm text-muted-foreground"
          role="status"
        >
          {data.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
      <main
        id="workspace-main"
        tabIndex={-1}
        className={cn(
          'mx-auto w-full min-w-0 flex-1 scroll-mt-24 p-5 md:p-8',
          employer ? 'max-w-[1500px]' : 'max-w-[1240px] md:py-12',
        )}
      >
        {children}
      </main>
      <footer className="double-rule mx-5 flex flex-wrap justify-between gap-2 py-5 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase md:mx-8">
        <span>Career Kitchen · {employer ? 'Kitchen' : 'Dining room'}</span>
        <span>A few introductions, made with care</span>
      </footer>
    </div>
  )
}
