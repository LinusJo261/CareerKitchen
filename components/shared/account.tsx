'use client'
import Link from 'next/link'
import { useTheme } from 'next-themes'
import { Bell, BellOff, CheckCheck, LogOut, Monitor, Moon, RotateCcw, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { EmptyNote, PageHeader, SectionTitle } from '@/components/workspace/kit'
import { useDemo } from '@/lib/demo/adapter'
import type { Role } from '@/lib/contracts'
import { cn } from '@/lib/utils'

export function NotificationsPage({ role }: { role: Role }) {
  const { data, update } = useDemo()
  const items = data.notifications.filter((n) => n.side === role)
  const unread = items.filter((n) => !n.read).length
  const markRead = (ids: string[]) => update((s) => ({ ...s, notifications: s.notifications.map((n) => ids.includes(n.id) ? { ...n, read: true } : n) }))
  return (
    <>
      <PageHeader eyebrow="Updates" title="Notifications" description="Only the things that genuinely need you." actions={unread > 0 && <Button variant="outline" onClick={() => markRead(items.map((n) => n.id))}><CheckCheck data-icon="inline-start" />Mark all as read</Button>} />
      {items.length === 0 ? <EmptyNote icon={BellOff} title="All quiet" description="We’ll let you know when something needs your attention." /> : (
        <ul className="panel divide-y">
          {items.map((n) => (
            <li key={n.id}>
              <Link href={n.href ?? `/${role}`} onClick={() => !n.read && markRead([n.id])} className="flex items-start gap-4 p-5 transition-colors hover:bg-muted">
                <span className={cn('mt-1 flex size-8 shrink-0 items-center justify-center rounded-full', n.read ? 'bg-muted text-muted-foreground' : 'bg-secondary text-primary')}><Bell className="size-4" /></span>
                <span className="flex-1"><span className={cn('block text-sm', !n.read && 'font-medium')}>{n.title}</span><span className="mt-1 block text-sm text-muted-foreground">{n.description}</span></span>
                {!n.read && <span className="mt-2 size-2 rounded-full bg-orange"><span className="sr-only">Unread</span></span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export function SettingsPage({ role }: { role: Role }) {
  const { data, update, reset } = useDemo()
  const { theme, setTheme } = useTheme()
  const pref = (key: keyof typeof data.preferences, value: boolean) => update((s) => ({ ...s, preferences: { ...s.preferences, [key]: value } }), 'Preference saved.')
  return (
    <>
      <PageHeader eyebrow="Account" title="Settings" description="Your account, appearance, and how we keep in touch." />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle title="Account" />
          <div className="panel flex flex-wrap items-center justify-between gap-4 p-5">
            <div><p className="font-medium">Alex Morgan</p><p className="text-sm text-muted-foreground">alex@example.com · {role === 'candidate' ? 'Candidate' : `${data.organization.name} · Owner`}</p></div>
            <Button variant="outline" asChild><Link href="/sign-in"><LogOut data-icon="inline-start" />Sign out</Link></Button>
          </div>
        </section>
        <section>
          <SectionTitle title="Appearance" />
          <ToggleGroup type="single" variant="outline" value={theme} onValueChange={(v) => v && setTheme(v)} aria-label="Color theme">
            <ToggleGroupItem value="light"><Sun />Light</ToggleGroupItem>
            <ToggleGroupItem value="dark"><Moon />Dark</ToggleGroupItem>
            <ToggleGroupItem value="system"><Monitor />System</ToggleGroupItem>
          </ToggleGroup>
        </section>
        <section>
          <SectionTitle title="Notifications" />
          <div className="panel divide-y">
            {([['email', 'Email updates', 'Decisions, mutual matches, and interview changes.'], ['digest', 'Weekly digest', 'A short summary every Monday morning.'], ['quietHours', 'Quiet hours', 'Hold non-urgent notifications between 8 PM and 8 AM.']] as const).map(([key, label, description]) => (
              <label key={key} className="flex cursor-pointer items-center justify-between gap-4 p-5">
                <span><span className="block text-sm font-medium">{label}</span><span className="block text-sm text-muted-foreground">{description}</span></span>
                <Switch checked={data.preferences[key]} onCheckedChange={(v) => pref(key, v)} />
              </label>
            ))}
          </div>
        </section>
        <section>
          <SectionTitle title="Demo environment" description="This workspace is fictional and runs entirely in your browser session." />
          <AlertDialog>
            <AlertDialogTrigger asChild><Button variant="outline"><RotateCcw data-icon="inline-start" />Reset demo data</Button></AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>Reset the demo?</AlertDialogTitle><AlertDialogDescription>All decisions, messages, and changes you’ve made in this session will be cleared.</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => reset()}>Reset</AlertDialogAction></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </section>
      </div>
    </>
  )
}
