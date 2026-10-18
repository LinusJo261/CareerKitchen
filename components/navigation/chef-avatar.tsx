import Image from 'next/image'
import { cn } from '@/lib/utils'

export function ChefAvatar({ className }: { className?: string }) {
  return (
    <span aria-hidden="true" className={cn('relative inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-flour', className)}>
      <Image src="/images/career-chef.png" alt="" width={96} height={96} className="size-full object-contain p-1" />
    </span>
  )
}
