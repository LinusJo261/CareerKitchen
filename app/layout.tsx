import type { Metadata, Viewport } from 'next'
import { Geist } from 'next/font/google'
import { Providers } from '@/components/providers'
import './globals.css'
const geist = Geist({subsets:['latin'],variable:'--font-geist'})
export const metadata:Metadata={title:{default:'Career Kitchen — Good things happen when the right people meet.',template:'%s | Career Kitchen'},description:'A more considered way to find your next role or your next great hire. Fewer applications. Mutual interest. Meaningful connections.'}
export const viewport:Viewport={themeColor:'#faf9f6',width:'device-width',initialScale:1}
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en" className="bg-background" suppressHydrationWarning><body className={`${geist.variable} font-sans`}><Providers>{children}</Providers></body></html>}
