/** Curated public guidance. These cards never call a model or read account data. */
export const chefGuides = [
  {
    id: 'candidate',
    title: 'Find my next role',
    description: 'A little prep for a more thoughtful search.',
    introduction: 'Start with what a good next step looks like for you. Here is the recipe.',
    steps: [
      { title: 'Set out your ingredients', text: 'Choose your role, work preferences and must-haves. In the demo, you can try the three-step setup without creating an account.', label: 'Start candidate setup', path: '/onboarding/candidate' },
      { title: 'Keep your plate manageable', text: 'Choose how many opportunities you want to consider, up to ten. Review the role details before expressing interest.', label: 'Explore Today’s Menu', path: '/candidate/opportunities' },
      { title: 'Meet when it is mutual', text: 'An introduction opens only after you and the employer both opt in. One-sided interest is still waiting for a response.', label: 'Understand your introductions', path: '/candidate/matches' },
    ],
  },
  {
    id: 'employer',
    title: 'Build my hiring team',
    description: 'Prepare a clear brief and meet with care.',
    introduction: 'A useful introduction starts with a clear role. Take it one course at a time.',
    steps: [
      { title: 'Prepare your organization', text: 'Review your organization details and team permissions. Demo verification labels describe fictional fixtures.', label: 'Visit your organization', path: '/employer/organization' },
      { title: 'Write an open order', text: 'Set the role requirements, compensation and work arrangement. Keep the active candidate capacity at ten or fewer.', label: 'Review your vacancies', path: '/employer/vacancies' },
      { title: 'Review, then introduce', text: 'Read candidate information and clarify unknowns. Conversations open when both sides agree to an introduction.', label: 'Explore The Pass', path: '/employer/pass' },
    ],
  },
  {
    id: 'introductions',
    title: 'How introductions work',
    description: 'Two yeses. A little room to pay attention.',
    introduction: 'Interest is an invitation. Both people get to decide whether to pull up a chair.',
    steps: [
      { title: 'Review a small selection', text: 'Candidates and vacancies each have an attention ceiling of ten, or a lower chosen limit. A smaller queue gives each introduction room.' },
      { title: 'Choose for yourself', text: 'Expressing interest does not send a message or create a mutual match. The other side must also opt in.' },
      { title: 'Continue at The Table', text: 'A mutual introduction opens the conversation. An introduction is not an offer, and an accepted offer is not a verified employment start.', label: 'See candidate introductions', path: '/candidate/matches' },
    ],
  },
  {
    id: 'privacy',
    title: 'Stay in control',
    description: 'Your preferences, your consent, your pace.',
    introduction: 'You decide what to share and which next steps to take.',
    steps: [
      { title: 'Choose what matters', text: 'Review your preferences and capacity before taking action. A suggested page or AI reply never makes a decision for you.', label: 'Review profile & preferences', path: '/candidate/profile' },
      { title: 'Check your consent', text: 'Evidence disclosure is scoped to its intended recipient and vacancy. Review your sharing choices in Privacy & consent.', label: 'Open privacy & consent', path: '/candidate/privacy' },
      { title: 'Ask Chef on your terms', text: 'These quick guides work without AI. Ask AI sends your question and recent chat history to Google Gemini only after you consent and send. Keep private details out of the chat.' },
    ],
  },
] as const

export type ChefGuideId = typeof chefGuides[number]['id']

export function chefContext(pathname: string) {
  const inSection = (section: string) => pathname === section || pathname.startsWith(`${section}/`)
  if (inSection('/onboarding/candidate')) return { label: 'A hand with your first steps', guide: 'candidate' as ChefGuideId, question: 'What should I include when setting up my candidate profile?' }
  if (inSection('/employer')) return { label: 'A little help with hiring', guide: 'employer' as ChefGuideId, question: 'How do I prepare a clear vacancy and review candidates?' }
  if (inSection('/candidate')) return { label: 'A little help with your next step', guide: 'candidate' as ChefGuideId, question: 'How can I make the most of my candidate profile and opportunities?' }
  return { label: 'Make yourself at home', guide: null, question: 'How do I get started with Career Kitchen?' }
}
