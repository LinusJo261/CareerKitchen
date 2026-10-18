'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useTheme } from 'next-themes'
import { toast } from 'sonner'
import {
  Bell,
  BellOff,
  CheckCheck,
  Download,
  LogOut,
  Monitor,
  Moon,
  RefreshCw,
  Sun,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { EmptyNote, PageHeader, SectionTitle } from '@/components/workspace/kit'
import { sendWorkspaceCommand, useWorkspace } from '@/lib/workspace'
import type { Notification, Role } from '@/lib/contracts'
import type { ApiSchema } from '@/lib/workspace-types'
import { cn } from '@/lib/utils'

export function NotificationsPage({ role }: { role: Role }) {
  const { data, refresh } = useWorkspace()
  const router = useRouter()
  const [pending, setPending] = useState(false)
  const items = data.notifications.filter(
    (notification) => notification.side === role,
  )
  const unread = items.filter((notification) => !notification.read)

  async function markRead(notifications: Notification[]) {
    if (pending) return
    setPending(true)
    try {
      for (const notification of notifications.filter((item) => !item.read)) {
        await sendWorkspaceCommand('notification.read', {
          id: notification.id,
          expected_version: notification.version,
        })
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to update notifications.',
      )
    } finally {
      await refresh().catch(() => undefined)
      setPending(false)
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Updates"
        title="Notifications"
        description="Updates from your workspace."
        actions={
          unread.length > 0 && (
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => markRead(unread)}
            >
              <CheckCheck data-icon="inline-start" />
              {pending ? 'Saving…' : 'Mark all as read'}
            </Button>
          )
        }
      />
      {items.length === 0 ? (
        <EmptyNote
          icon={BellOff}
          title="All quiet"
          description="Your account notifications will appear here."
        />
      ) : (
        <ul className="panel divide-y">
          {items.map((notification) => (
            <li key={notification.id}>
              <Link
                href={notification.href ?? `/${role}`}
                onClick={async (event) => {
                  if (
                    event.button !== 0 ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return
                  event.preventDefault()
                  if (!notification.read) await markRead([notification])
                  router.push(notification.href ?? `/${role}`)
                }}
                className="flex items-start gap-4 p-5 transition-colors hover:bg-muted"
              >
                <span
                  className={cn(
                    'mt-1 flex size-8 shrink-0 items-center justify-center rounded-full',
                    notification.read
                      ? 'bg-muted text-muted-foreground'
                      : 'bg-secondary text-primary',
                  )}
                >
                  <Bell className="size-4" />
                </span>
                <span className="flex-1">
                  <span
                    className={cn(
                      'block text-sm',
                      !notification.read && 'font-medium',
                    )}
                  >
                    {notification.title}
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">
                    {notification.description}
                  </span>
                </span>
                {!notification.read && (
                  <span className="mt-2 size-2 rounded-full bg-orange">
                    <span className="sr-only">Unread</span>
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

export function SettingsPage({ role }: { role: Role }) {
  const { data, execute } = useWorkspace()
  const { theme, setTheme } = useTheme()
  const [saving, setSaving] = useState(false)
  const [signingOut, setSigningOut] = useState(false)
  const notificationPreferences = data.backend.notificationPreferences
  const membership = data.session?.memberships.find(
    (member) => member.org_id === data.context.organizationId,
  )

  async function preference(
    key: 'email_opt_in' | 'in_app_opt_in' | 'quiet_hours',
    value: boolean,
  ) {
    if (saving) return
    setSaving(true)
    const quietHours = value
      ? {
          start: '20:00',
          end: '08:00',
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }
      : {}
    try {
      await execute(
        'notifications.preferences',
        {
          expected_version: notificationPreferences.version,
          email_opt_in: notificationPreferences.email_opt_in,
          in_app_opt_in: notificationPreferences.in_app_opt_in,
          quiet_hours: notificationPreferences.quiet_hours,
          [key]: key === 'quiet_hours' ? quietHours : value,
        },
        'Notification preferences saved.',
      )
    } finally {
      setSaving(false)
    }
  }

  async function signOut() {
    if (signingOut) return
    setSigningOut(true)
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST' })
      if (!response.ok) throw new Error('Unable to sign out. Please try again.')
      window.location.replace('/sign-in')
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Unable to sign out.',
      )
      setSigningOut(false)
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Settings"
        description="Your account, appearance, and how we keep in touch."
      />
      <div className="flex max-w-3xl flex-col gap-10">
        <section>
          <SectionTitle title="Account" />
          <div className="panel flex flex-wrap items-center justify-between gap-4 p-5">
            <div>
              <p className="font-medium">{data.session?.email}</p>
              <p className="text-sm text-muted-foreground">
                {role === 'candidate'
                  ? 'Candidate workspace'
                  : `${data.organization.name}${membership ? ` · ${membership.role.replaceAll('_', ' ').toLowerCase()}` : ''}`}
              </p>
            </div>
            <Button variant="outline" disabled={signingOut} onClick={signOut}>
              <LogOut data-icon="inline-start" />
              {signingOut ? 'Signing out…' : 'Sign out'}
            </Button>
          </div>
        </section>
        <section>
          <SectionTitle title="Appearance" />
          <ToggleGroup
            type="single"
            variant="outline"
            value={theme}
            onValueChange={(value) => value && setTheme(value)}
            aria-label="Color theme"
          >
            <ToggleGroupItem value="light">
              <Sun />
              Light
            </ToggleGroupItem>
            <ToggleGroupItem value="dark">
              <Moon />
              Dark
            </ToggleGroupItem>
            <ToggleGroupItem value="system">
              <Monitor />
              System
            </ToggleGroupItem>
          </ToggleGroup>
        </section>
        <section>
          <SectionTitle title="Notifications" />
          <div className="panel divide-y">
            {(
              [
                [
                  'email_opt_in',
                  'Email updates',
                  'Allow email delivery for account updates.',
                  notificationPreferences.email_opt_in,
                ],
                [
                  'in_app_opt_in',
                  'In-app updates',
                  'Allow notifications in this workspace.',
                  notificationPreferences.in_app_opt_in,
                ],
                [
                  'quiet_hours',
                  'Quiet hours',
                  'Save a quiet period from 8 PM to 8 AM in your current timezone.',
                  Object.keys(notificationPreferences.quiet_hours ?? {})
                    .length > 0,
                ],
              ] as const
            ).map(([key, label, description, checked]) => (
              <label
                key={key}
                className="flex cursor-pointer items-center justify-between gap-4 p-5"
              >
                <span>
                  <span className="block text-sm font-medium">{label}</span>
                  <span className="block text-sm text-muted-foreground">
                    {description}
                  </span>
                </span>
                <Switch
                  checked={checked}
                  disabled={saving}
                  onCheckedChange={(value) => preference(key, value)}
                />
              </label>
            ))}
          </div>
        </section>
        <PrivacyControls />
      </div>
    </>
  )
}

function PrivacyControls() {
  const { data, refresh } = useWorkspace()
  const [exportJob, setExportJob] = useState<ApiSchema['ExportOut'] | null>(
    null,
  )
  const [deletion, setDeletion] = useState<ApiSchema['OperationOut'] | null>(
    null,
  )
  const [pending, setPending] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const job = exportJob ?? data.backend.privacyExport

  async function run(
    action: 'privacy.export' | 'privacy.export.status' | 'privacy.delete',
  ) {
    if (pending) return
    setPending(action)
    try {
      if (action === 'privacy.delete') {
        const result =
          await sendWorkspaceCommand<ApiSchema['OperationOut']>(action)
        setDeletion(result)
        setDeleteOpen(false)
      } else if (action === 'privacy.export.status') {
        setExportJob(await sendWorkspaceCommand<ApiSchema['ExportOut']>(action))
        await refresh()
      } else {
        const result =
          await sendWorkspaceCommand<ApiSchema['OperationOut']>(action)
        setExportJob({
          operation_id: result.operation_id,
          status: result.status,
          export: null,
        })
        await refresh()
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : 'Unable to complete your privacy request.',
      )
    } finally {
      setPending(null)
    }
  }

  function download() {
    if (!job?.export || job.status !== 'COMPLETE') return
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(job.export, null, 2)], {
        type: 'application/json',
      }),
    )
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `career-kitchen-export-${job.operation_id}.json`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <section>
      <SectionTitle
        title="Your data"
        description="Export your account data or request account deletion."
      />
      <div className="panel flex flex-col gap-5 p-5">
        <div>
          <p className="text-sm font-medium">Data export</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Exports are prepared by the backend worker. Check the status here
            and download the JSON once it is ready.
          </p>
          {job && (
            <p
              className="mt-2 break-all text-xs text-muted-foreground"
              role="status"
            >
              Request {job.operation_id} ·{' '}
              {job.status.replaceAll('_', ' ').toLowerCase()}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="outline"
              disabled={
                pending !== null ||
                (!!job && ['PENDING', 'PROCESSING'].includes(job.status))
              }
              onClick={() => run('privacy.export')}
            >
              <Download data-icon="inline-start" />
              Request export
            </Button>
            {job && (
              <Button
                variant="outline"
                disabled={pending !== null}
                onClick={() => run('privacy.export.status')}
              >
                <RefreshCw data-icon="inline-start" />
                Check status
              </Button>
            )}
            {job?.status === 'COMPLETE' && job.export && (
              <Button onClick={download}>Download JSON</Button>
            )}
          </div>
        </div>
        <div className="border-t pt-5">
          <p className="text-sm font-medium">Delete account</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Matching stops immediately when deletion is requested. Retained
            audit records and deletion at external providers require a separate
            review. You must have signed in within the last 10 minutes.
          </p>
          {deletion ? (
            <p className="mt-3 text-sm" role="status">
              Deletion request {deletion.operation_id}:{' '}
              {deletion.status.replaceAll('_', ' ').toLowerCase()}.{' '}
              {deletion.notice}
            </p>
          ) : (
            <AlertDialog
              open={deleteOpen}
              onOpenChange={(value) => !pending && setDeleteOpen(value)}
            >
              <AlertDialogTrigger asChild>
                <Button
                  className="mt-3"
                  variant="destructive"
                  disabled={pending !== null}
                >
                  <Trash2 data-icon="inline-start" />
                  Request account deletion
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Request account deletion?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This deactivates your account, closes your active matches,
                    and revokes shared candidate disclosures immediately. Some
                    records require retention or provider review.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel disabled={pending !== null}>
                    Cancel
                  </AlertDialogCancel>
                  <AlertDialogAction
                    disabled={pending !== null}
                    onClick={(event) => {
                      event.preventDefault()
                      void run('privacy.delete')
                    }}
                  >
                    {pending
                      ? 'Submitting…'
                      : 'Deactivate and request deletion'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>
    </section>
  )
}
