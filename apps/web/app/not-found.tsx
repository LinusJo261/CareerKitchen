import Link from 'next/link'
import { Button } from '@/components/ui/button'

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
      <p className="eyebrow">Not found</p>
      <h1 className="text-3xl font-medium text-balance">This page isn’t on the menu.</h1>
      <p className="text-muted-foreground">The link may be outdated, or the page has moved.</p>
      <Button asChild><Link href="/">Back to home</Link></Button>
    </main>
  )
}
