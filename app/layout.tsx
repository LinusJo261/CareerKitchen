import type { Metadata, Viewport } from 'next'
import { DM_Mono, DM_Sans, Fraunces } from 'next/font/google'
import { Providers } from '@/components/providers'
import { CareerChefProvider } from '@/components/navigation/career-chef-provider'
import './globals.css'

const fraunces = Fraunces({ subsets: ['latin'], variable: '--font-fraunces', axes: ['SOFT', 'WONK', 'opsz'] })
const dmSans = DM_Sans({ subsets: ['latin'], variable: '--font-dm-sans' })
const dmMono = DM_Mono({ subsets: ['latin'], weight: ['400', '500'], variable: '--font-dm-mono' })

export const metadata: Metadata = {
  title: { default: 'Career Kitchen — A few introductions, made with care.', template: '%s · Career Kitchen' },
  description:
    'Career Kitchen is a two-sided career matching platform. Global allocation, budgeted verification, and employer-scoped repair produce a small set of mutually relevant introductions.',
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f7f2e8' },
    { media: '(prefers-color-scheme: dark)', color: '#282521' },
  ],
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`bg-background ${fraunces.variable} ${dmSans.variable} ${dmMono.variable}`} suppressHydrationWarning>
      <body className="font-sans">
        <Providers><CareerChefProvider>{children}</CareerChefProvider></Providers>
      </body>
    </html>
  )
}
