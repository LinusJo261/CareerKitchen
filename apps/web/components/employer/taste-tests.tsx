'use client'
import Link from 'next/link'
import { FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { EmptyNote, PageHeader } from '@/components/workspace/kit'
import { tasteTestsLeft, usePass } from '@/lib/demo/pass'

export function TasteTestsPage() {
  const pass = usePass()
  const left = tasteTestsLeft(pass)
  return (
    <>
      <PageHeader
        eyebrow={`Ticket ${pass.order.ticket}`}
        title="Taste Tests"
        description={`Verification questions sent to candidates. ${left} of ${pass.order.verificationBudget} left for this order.`}
        actions={<Button asChild><Link href="/employer/pass">Send from The Pass</Link></Button>}
      />
      {pass.tasteTests.length === 0 ? (
        <EmptyNote icon={FlaskConical} title="No taste tests sent" description="Open a candidate on The Pass and send a question about anything marked inferred or unknown." />
      ) : (
        <ul className="flex flex-col gap-4">
          {pass.tasteTests.map((t) => {
            const name = pass.candidates.find((c) => c.id === t.candidateId)?.name ?? 'Candidate'
            return (
              <li key={t.id} className="panel flex flex-col gap-3 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">{name} · {t.topic}</p>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">Sent {t.sent}</span>
                    <Badge variant={t.status === 'Answered' ? 'secondary' : 'outline'}>{t.status}</Badge>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground text-pretty">{t.question}</p>
                {t.answer && <p className="border-l-2 border-primary pl-3 text-sm text-pretty">{t.answer}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
