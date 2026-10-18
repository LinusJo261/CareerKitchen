// Fictional demo data. Every person, company, and record here is invented.
import type { DemoState } from '@/lib/contracts'

export const initialState: DemoState = {
  revision: 0,
  profile: {
    id: 'alex', name: 'Alex Morgan', title: 'Senior Product Designer', location: 'Brooklyn, New York',
    skills: ['Product design', 'Design systems', 'Figma', 'User research'],
    summary: 'Thoughtful product designer turning complex problems into simple, human experiences. Six years building products with early-stage teams.',
    capacity: 5, availability: 'Within 4 weeks', experience: '6 years', compensation: '$140,000 – $175,000', remote: 'Remote or hybrid', privacy: true,
    industries: ['Productivity', 'Fintech'], roles: ['Product designer', 'Design systems lead'],
    requirements: { Compensation: 'Must-have', 'Remote flexibility': 'Must-have', 'Team size': 'Preference', Industry: 'Flexible' },
  },
  organization: { id: 'forma', name: 'Forma', verified: true, description: 'Building a calmer, more connected way to work.', domain: 'forma.example', verification: 'Verified' },
  opportunities: [
    { id: 'o1', title: 'Senior Product Designer', company: 'Forma', salary: '$150,000 – $175,000', location: 'New York, NY', arrangement: 'Hybrid', skills: ['Product design', 'Design systems', 'B2B SaaS'], summary: 'Help shape the next chapter of collaborative work. Join a small, design-led team building thoughtful tools that bring people and ideas together.', deadline: 'Oct 22', verified: true, employerInterested: true, status: 'Active', employmentType: 'Full-time', reason: 'Your design systems experience and preference for a small, collaborative team align with this role.', required: ['5+ years of product design', 'Shipped a design system'], responsibilities: ['Own the core collaboration surfaces', 'Evolve the design system with engineering'], workflow: ['Introduction', 'Portfolio interview', 'Offer review'] },
    { id: 'o2', title: 'Founding Product Designer', company: 'Layers', salary: '$155,000 – $185,000', location: 'United States', arrangement: 'Remote', skills: ['Product design', '0 to 1 products', 'Figma'], summary: 'Own the design experience from the very first sketch to a product people love. Work directly with the founders on a new creative platform.', deadline: 'Oct 24', verified: true, employerInterested: false, status: 'Active', employmentType: 'Full-time', reason: 'A hands-on role with the ownership and remote flexibility you are looking for.', required: ['Shipped a 0 to 1 product', 'Strong visual craft'], responsibilities: ['Define the product’s first design language', 'Run research with early users'], workflow: ['Founder conversation', 'Design exercise', 'Offer review'] },
    { id: 'o3', title: 'Product Designer, Growth', company: 'Northstar', salary: '$140,000 – $165,000', location: 'San Francisco, CA', arrangement: 'Remote', skills: ['User research', 'Experimentation', 'Product design'], summary: 'Make everyday financial decisions feel clear and approachable. Bring research and thoughtful experimentation to our growth team.', deadline: 'Oct 25', verified: true, employerInterested: true, status: 'Active', employmentType: 'Full-time', reason: 'Combines your research background with your interest in meaningful consumer products.', required: ['4+ years of product design', 'Experience running experiments'], responsibilities: ['Design and test onboarding improvements', 'Partner with data science on learning agendas'], workflow: ['Introduction', 'Portfolio interview', 'Team conversation'] },
  ],
  vacancies: [
    { id: 'v1', title: 'Senior Product Designer', company: 'Forma', salary: '$150,000 – $175,000', location: 'New York, NY', arrangement: 'Hybrid', skills: ['Product design', 'Design systems'], summary: 'Shape collaborative tools with a small, design-led team.', deadline: 'Nov 30', verified: true, employerInterested: false, status: 'Active', employmentType: 'Full-time' },
    { id: 'v2', title: 'Staff Frontend Engineer', company: 'Forma', salary: '$185,000 – $215,000', location: 'Remote, US', arrangement: 'Remote', skills: ['React', 'TypeScript', 'Accessibility'], summary: 'Lead the frontend architecture of our collaboration canvas.', deadline: 'Dec 12', verified: true, employerInterested: false, status: 'Active', employmentType: 'Full-time' },
    { id: 'v3', title: 'Research Operations Lead', company: 'Forma', salary: '$120,000 – $140,000', location: 'New York, NY', arrangement: 'Hybrid', skills: ['Research ops', 'Program management'], summary: 'Build the systems that help every team learn from customers.', deadline: 'Not set', verified: true, employerInterested: false, status: 'Draft', employmentType: 'Full-time' },
  ],
  candidates: [
    { id: 'c1', name: 'Jamie Chen', title: 'Senior Product Designer', location: 'New York, NY', skills: ['Product design', 'Design systems', 'Figma'], summary: 'A systems-minded designer with 7 years of experience making complex workflows feel simple.', capacity: 4, availability: 'Within 4 weeks', experience: '7 years', compensation: 'Not disclosed', remote: 'Hybrid', privacy: true },
    { id: 'c2', name: 'Taylor Brooks', title: 'Product Designer', location: 'Austin, TX', skills: ['User research', 'Interaction design', 'Prototyping'], summary: 'Research-led product designer focused on inclusive, thoughtful digital experiences.', capacity: 3, availability: 'Within 6 weeks', experience: '5 years', compensation: 'Not disclosed', remote: 'Remote', privacy: true },
    { id: 'c3', name: 'Sam Rivera', title: 'Senior Product Designer', location: 'Brooklyn, NY', skills: ['B2B SaaS', 'Design systems', 'Product strategy'], summary: 'Building useful tools for people at work, with a focus on craft and collaboration.', capacity: 5, availability: 'Within 2 weeks', experience: '6 years', compensation: 'Not disclosed', remote: 'Hybrid', privacy: true },
  ],
  decisions: {},
  candidateDecisions: {},
  matches: [
    { id: 'm1', opportunityId: 'other1', name: 'Morgan Lee', role: 'Product Designer', company: 'Gather', stage: 'Interviewing', updated: 'Today' },
    { id: 'm2', opportunityId: 'other2', name: 'Jordan Park', role: 'Senior Product Designer', company: 'Daylight', stage: 'Mutual interest', updated: 'Yesterday' },
    { id: 'm3', opportunityId: 'other3', name: 'Riley Shah', role: 'Senior Product Designer', company: 'Fieldwork', stage: 'Offer', updated: 'Oct 15' },
  ],
  pipeline: [
    { id: 'p1', name: 'Jamie Chen', title: 'Senior Product Designer', vacancy: 'Senior Product Designer', stage: 'Introduced', interest: 'Awaiting you', updated: 'Today', verifiedEvidence: 2, skills: ['Design systems', 'Figma'] },
    { id: 'p2', name: 'Avery Kim', title: 'Product Designer', vacancy: 'Senior Product Designer', stage: 'Mutual interest', interest: 'Mutual', updated: 'Yesterday', verifiedEvidence: 1, skills: ['Prototyping', 'Research'] },
    { id: 'p3', name: 'Casey Nguyen', title: 'Senior Product Designer', vacancy: 'Senior Product Designer', stage: 'Interviewing', interest: 'Mutual', updated: 'Oct 15', verifiedEvidence: 2, skills: ['B2B SaaS', 'Design systems'] },
    { id: 'p4', name: 'Drew Patel', title: 'Staff Frontend Engineer', vacancy: 'Staff Frontend Engineer', stage: 'Interviewing', interest: 'Mutual', updated: 'Oct 14', verifiedEvidence: 1, skills: ['React', 'Accessibility'] },
    { id: 'p5', name: 'Robin Ortiz', title: 'Senior Frontend Engineer', vacancy: 'Staff Frontend Engineer', stage: 'Offer', interest: 'Mutual', updated: 'Oct 12', verifiedEvidence: 3, skills: ['TypeScript', 'Performance'] },
    { id: 'p6', name: 'Quinn Adler', title: 'Frontend Engineer', vacancy: 'Staff Frontend Engineer', stage: 'Introduced', interest: 'Awaiting candidate', updated: 'Oct 16', verifiedEvidence: 0, skills: ['React', 'Design systems'] },
  ],
  interviews: [
    { id: 'i1', side: 'candidate', company: 'Gather', role: 'Product Designer', person: 'Morgan Lee', date: '2026-10-21', time: '10:30 AM ET', format: 'Video · Portfolio conversation', status: 'Scheduled' },
    { id: 'i2', side: 'employer', company: 'Forma', role: 'Senior Product Designer', person: 'Casey Nguyen', date: '2026-10-20', time: '2:00 PM ET', format: 'Video · Portfolio interview', status: 'Confirmed' },
    { id: 'i3', side: 'employer', company: 'Forma', role: 'Staff Frontend Engineer', person: 'Drew Patel', date: '2026-10-22', time: '11:00 AM ET', format: 'On-site · Architecture conversation', status: 'Scheduled' },
  ],
  offers: [{ id: 'f1', company: 'Fieldwork', role: 'Senior Product Designer', salary: '$165,000 / year', deadline: 'October 28, 2026', start: 'November 16, 2026', status: 'Awaiting response' }],
  policy: {
    id: 'pact1', role: 'Senior Product Designer', version: 'v1.0', compensation: '$150,000 – $175,000 USD / year', arrangement: 'Hybrid · New York · 2 days in office',
    requirements: ['5+ years of product design experience', 'Experience shipping a design system'],
    evidence: ['Portfolio case study', 'Employment history attestation'],
    stages: ['Introduction', 'Portfolio interview', 'Offer review'],
    authority: 'Hiring manager may approve introductions and interviews. Offers require organization approval.',
    expires: '2026-11-30', revocation: 'Either party may revoke at any time. Terms expire automatically if the role version changes.',
    status: 'Draft', candidateConfirmed: false,
  },
  consents: [
    { id: 's1', label: 'Portfolio and selected case studies', recipient: 'Forma', purpose: 'Evaluate design systems experience for Senior Product Designer v1.0.', expires: 'November 30, 2026', granted: true },
    { id: 's2', label: 'Employment history attestation', recipient: 'Forma', purpose: 'Confirm the essential experience requirement for this role only.', expires: 'November 30, 2026', granted: false },
    { id: 's3', label: 'Current location (city only)', recipient: 'Northstar', purpose: 'Confirm time-zone overlap for a remote role.', expires: 'October 31, 2026', granted: true },
  ],
  evidence: [
    { id: 'e1', name: 'Portfolio case study', status: 'Verified', issuer: 'Demo verification record' },
    { id: 'e2', name: 'Employment history', status: 'Pending', issuer: 'Awaiting candidate attestation' },
    { id: 'e3', name: 'Professional references', status: 'Not shared', issuer: 'Only shared with your permission' },
  ],
  clarifications: [
    { id: 'w1', kind: 'Requirement clarification', title: 'Clarify the on-site requirement', description: 'The role lists both “remote-friendly” and “two days in the New York office.”', why: 'Candidates with a remote must-have may pass on an ambiguous listing. A clear arrangement lets them decide with accurate information.', action: 'Update arrangement to “Hybrid, two days in office”', status: 'Pending' },
    { id: 'w2', kind: 'Decision-maker unavailable', title: 'Assign an authorized interviewer', description: 'A portfolio interview is ready to be arranged, but no authorized interviewer is assigned.', why: 'Mutual matches are waiting on scheduling. Assigning an interviewer lets the next step proceed.', action: 'Assign the hiring manager as interviewer', status: 'Pending' },
    { id: 'w3', kind: 'Missing attestation', title: 'Evidence requirement not yet listed', description: 'PACT terms ask for an employment history attestation, but the job opening does not mention it.', why: 'Candidates can only consent to disclosures they can see. Listing it keeps terms and the job opening consistent.', action: 'Add the attestation to the job opening’s evidence list', status: 'Pending' },
  ],
  notifications: [
    { id: 'n1', side: 'candidate', title: 'Three introductions, thoughtfully selected', description: 'Your new opportunities are ready when you are.', read: false, href: '/candidate/opportunities' },
    { id: 'n2', side: 'candidate', title: 'Portfolio conversation with Gather', description: 'Wednesday, October 21 at 10:30 AM ET.', read: false, href: '/candidate/interviews' },
    { id: 'n3', side: 'candidate', title: 'Fieldwork shared an offer', description: 'Please respond by October 28.', read: true, href: '/candidate/offers' },
    { id: 'n4', side: 'employer', title: 'Three candidates ready for review', description: 'Senior Product Designer · consented profiles.', read: false, href: '/employer/candidates' },
    { id: 'n5', side: 'employer', title: 'A hiring condition needs attention', description: 'WITNESS found three items you can resolve.', read: false, href: '/employer/witness' },
  ],
  conversations: [
    { id: 't1', side: 'candidate', name: 'Morgan Lee', company: 'Gather', role: 'Talent partner', messages: [
      { id: 'msg1', text: 'Hi Alex! We loved the thoughtfulness in your portfolio. Would you be open to walking us through your design systems work?', mine: false, time: '9:41 AM' },
      { id: 'msg2', text: 'Absolutely. I would love to share more about the process and meet the team.', mine: true, time: '9:45 AM' },
      { id: 'msg3', text: 'Wonderful. I have sent a portfolio conversation invitation for Wednesday. Looking forward to it!', mine: false, time: '9:48 AM' },
    ] },
    { id: 't2', side: 'candidate', name: 'Jordan Park', company: 'Daylight', role: 'Design lead', messages: [
      { id: 'msg4', text: 'Great to meet you, Alex. What are you hoping to explore in your next role?', mine: false, time: 'Yesterday' },
    ] },
    { id: 't3', side: 'employer', name: 'Casey Nguyen', company: 'Candidate', role: 'Senior Product Designer', messages: [
      { id: 'msg5', text: 'Thanks for the invitation. Monday at 2 PM works well for me.', mine: false, time: '8:12 AM' },
      { id: 'msg6', text: 'Perfect — you’ll receive a calendar invite shortly. Feel free to bring any work you’re proud of.', mine: true, time: '8:20 AM' },
    ] },
    { id: 't4', side: 'employer', name: 'Avery Kim', company: 'Candidate', role: 'Product Designer', messages: [
      { id: 'msg7', text: 'Hi! Excited about the mutual match. Is the role open to a January start?', mine: false, time: 'Yesterday' },
    ] },
  ],
  team: [
    { id: 'u1', name: 'Alex Morgan', email: 'alex@forma.example', role: 'Owner' },
    { id: 'u2', name: 'Morgan Lee', email: 'morgan@forma.example', role: 'Recruiter' },
    { id: 'u3', name: 'Priya Desai', email: 'priya@forma.example', role: 'Hiring manager' },
  ],
  preferences: { email: true, digest: true, quietHours: false },
}
