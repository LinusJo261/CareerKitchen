import { Shell } from '@/components/workspace/shell'

export default function Layout({ children }: { children: React.ReactNode }) {
  return <Shell role="candidate">{children}</Shell>
}
