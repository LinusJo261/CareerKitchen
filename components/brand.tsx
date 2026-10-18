import Link from 'next/link'
import { cn } from '@/lib/utils'

/** The mark is a tiny order ticket: perforated top, serif monogram. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn('ticket flex h-8 w-7 shrink-0 items-end justify-center bg-primary pb-1 text-primary-foreground', className)}>
      <span className="font-serif text-[15px] leading-none italic" style={{ fontVariationSettings: "'opsz' 72, 'WONK' 1" }}>
        ck
      </span>
    </span>
  )
}

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link href="/" aria-label="Career Kitchen home" className={cn('group flex w-fit items-center gap-2.5 rounded-sm', className)}>
      <BrandMark />
      {!compact && (
        <span className="font-serif text-[21px] leading-none tracking-tight whitespace-nowrap">
          Career <span className="italic">Kitchen</span>
        </span>
      )}
    </Link>
  )
}

export function CompanyMark({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn('flex size-11 shrink-0 items-center justify-center rounded-sm border border-foreground/15 bg-background font-serif text-xl italic text-primary', className)}
    >
      {name.slice(0, 1)}
    </span>
  )
}
