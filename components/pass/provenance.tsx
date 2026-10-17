import { cn } from '@/lib/utils'
import type { Provenance } from '@/lib/contracts'
import type { Line } from '@/lib/demo/pass'

export const provenanceLabel: Record<Provenance, string> = { confirmed: 'Confirmed', inferred: 'Inferred', unknown: 'Unknown' }

/** Solid = confirmed, half-filled = inferred, dashed ring = unknown. Shape carries meaning, not color alone. */
export function ProvenanceGlyph({ status, className }: { status: Provenance; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-block size-2.5 shrink-0 rounded-full',
        status === 'confirmed' && 'bg-current',
        status === 'inferred' && 'border-[1.5px] border-current bg-[linear-gradient(90deg,currentColor_50%,transparent_50%)]',
        status === 'unknown' && 'border-[1.5px] border-dashed border-current',
        className,
      )}
    />
  )
}

export const stateTone: Record<Line['state'], string> = {
  met: 'text-primary',
  missed: 'text-paprika-ink',
  open: 'text-muted-foreground',
}
export const stateWord: Record<Line['state'], string> = { met: 'Yes', missed: 'No', open: '?' }

export function ProvenanceLegend({ className }: { className?: string }) {
  return (
    <dl className={cn('flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px] tracking-[0.1em] text-muted-foreground uppercase', className)}>
      {(['confirmed', 'inferred', 'unknown'] as const).map((p) => (
        <div key={p} className="flex items-center gap-2">
          <dt className="text-foreground"><ProvenanceGlyph status={p} /></dt>
          <dd>{provenanceLabel[p]}</dd>
        </div>
      ))}
    </dl>
  )
}
