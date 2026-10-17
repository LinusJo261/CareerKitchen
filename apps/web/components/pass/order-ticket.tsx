'use client'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { passActions, repairs, tasteTestsLeft } from '@/lib/demo/pass'
import { cn } from '@/lib/utils'
import type { Arrangement, PassState, RecipeWeight } from '@/lib/contracts'

const weightItem = 'font-mono text-[11px] tracking-[0.1em] uppercase data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:hover:bg-primary'

export function OrderTicket({ state }: { state: PassState }) {
  const { order } = state
  const left = tasteTestsLeft(state)
  const notes = repairs(state)

  return (
    <section aria-labelledby="order-title" className="ticket-shadow">
      <div className="ticket px-6 pt-8 pb-6">
        <div className="flex items-baseline justify-between font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase">
          <span>Order No. {order.ticket}</span>
          <span>{order.company}</span>
        </div>
        <h2 id="order-title" className="mt-3 text-3xl leading-tight text-balance">{order.title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">Edit the recipe. Tickets on the pass respond as you go.</p>

        <div className="rule-dashed my-5" />
        <h3 className="eyebrow">Recipe</h3>
        <ul className="mt-3 flex flex-col gap-4">
          {order.recipe.map((r) => (
            <li key={r.id} className="flex flex-col gap-1.5">
              <span id={`recipe-${r.id}`} className={cn('text-sm leading-snug', r.weight === 'off' && 'text-muted-foreground line-through decoration-foreground/30')}>
                {r.label}
              </span>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={r.weight}
                aria-labelledby={`recipe-${r.id}`}
                onValueChange={(v) => v && passActions.setWeight(r.id, v as RecipeWeight)}
              >
                <ToggleGroupItem value="must" className={weightItem}>Must</ToggleGroupItem>
                <ToggleGroupItem value="nice" className={weightItem}>Nice</ToggleGroupItem>
                <ToggleGroupItem value="off" className={weightItem}>Off</ToggleGroupItem>
              </ToggleGroup>
            </li>
          ))}
        </ul>

        <div className="rule-dashed my-5" />
        <h3 className="eyebrow">Terms</h3>
        <div className="mt-3 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <span id="order-arrangement" className="text-sm">Work arrangement</span>
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={order.arrangement}
              aria-labelledby="order-arrangement"
              onValueChange={(v) => v && passActions.setArrangement(v as Arrangement)}
            >
              <ToggleGroupItem value="Hybrid · NYC 2 days" className={weightItem}>Hybrid NYC</ToggleGroupItem>
              <ToggleGroupItem value="Remote (US)" className={weightItem}>Remote US</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span id="order-ceiling" className="text-sm">Base salary ceiling</span>
            <div role="group" aria-labelledby="order-ceiling" className="flex items-center gap-1">
              <Button variant="outline" size="icon" aria-label="Lower ceiling by $5k" disabled={order.ceiling <= 140} onClick={() => passActions.setCeiling(order.ceiling - 5)}>
                <Minus />
              </Button>
              <output aria-live="polite" className="w-16 text-center font-mono text-sm">${order.ceiling}k</output>
              <Button variant="outline" size="icon" aria-label="Raise ceiling by $5k" disabled={order.ceiling >= 220} onClick={() => passActions.setCeiling(order.ceiling + 5)}>
                <Plus />
              </Button>
            </div>
          </div>
        </div>

        <div className="rule-dashed my-5" />
        <div className="flex items-center justify-between gap-3">
          <h3 className="eyebrow">Taste tests left</h3>
          <span className="flex items-center gap-1.5" aria-label={`${left} of ${order.verificationBudget} remaining`}>
            {Array.from({ length: order.verificationBudget }, (_, i) => (
              <span key={i} aria-hidden="true" className={cn('size-3 rounded-[2px] border border-primary', i < left && 'bg-primary')} />
            ))}
            <span className="ml-1 font-mono text-xs">{left}/{order.verificationBudget}</span>
          </span>
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
          Each order gets a small verification budget, so candidates are only asked questions that matter.
        </p>

        <div className="mt-6 rounded-sm bg-accent p-4 text-accent-foreground">
          <h3 className="font-serif text-lg italic">Kitchen notes</h3>
          <p className="text-xs leading-relaxed opacity-80">Single changes to this order that would qualify more people. You choose whether to apply them.</p>
          {notes.length === 0 ? (
            <p className="mt-3 text-sm">No single change would qualify anyone else right now.</p>
          ) : (
            <ul className="mt-3 flex flex-col gap-3">
              {notes.slice(0, 3).map((n) => (
                <li key={n.id} className="flex flex-col gap-2 border-t border-foreground/15 pt-3">
                  <div>
                    <p className="text-sm font-medium">{n.title}</p>
                    <p className="text-xs opacity-80">Would qualify {n.names.join(', ')}. {n.detail}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="self-start bg-transparent"
                    onClick={() => {
                      passActions.applyOrder(n.next, n.title)
                      toast.success('Kitchen note applied', { description: n.title })
                    }}
                  >
                    Apply note
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Button variant="ghost" size="sm" className="mt-4 text-muted-foreground" onClick={() => { passActions.reset(); toast('Demo order restored') }}>
          <RotateCcw data-icon="inline-start" />
          Reset demo order
        </Button>
      </div>
    </section>
  )
}
