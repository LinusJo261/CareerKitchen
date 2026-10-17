import Link from 'next/link'
import { cn } from '@/lib/utils'
export function Brand({compact=false}:{compact?:boolean}){return <Link href="/" aria-label="Career Kitchen home" className="flex items-center gap-2.5 text-primary"><span className="brand-mark" aria-hidden="true"/>{!compact&&<span className="text-xl font-semibold tracking-[-.065em] text-foreground">career kitchen<span className="text-primary">.</span></span>}</Link>}
export function CompanyMark({name,className}:{name:string;className?:string}){return <span aria-hidden="true" className={cn('flex size-11 shrink-0 items-center justify-center rounded-xl bg-secondary text-primary text-xl font-semibold',className)}>{name==='Forma'?'f':name==='Layers'?'≋':name==='Northstar'?'✳':name.slice(0,1)}</span>}
