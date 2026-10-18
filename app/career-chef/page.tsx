import type { Metadata } from 'next'
import { CareerChefPage } from '@/components/navigation/career-chef-page'

export const metadata: Metadata = {
  title: 'Career Chef',
  description: 'Ask Career Chef for help navigating Career Kitchen, powered by Google Gemini.',
}

export default function Page() {
  return <CareerChefPage />
}
