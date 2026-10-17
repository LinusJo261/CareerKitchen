# Career Kitchen

### Better matches. Fewer applications. A smarter job market.

**Career Kitchen** is a two-sided hiring platform that reimagines job matching as a global optimization problem.

Traditional job platforms help candidates discover opportunities and employers filter applications. Career Kitchen takes a different approach: rather than optimizing each recommendation independently, it coordinates matching across the entire market to identify high-quality, mutually beneficial opportunities while reducing unnecessary applications and hiring friction.

**Built for DubHacks 2026.**

---

## The Problem

Hiring has become increasingly inefficient.

**For candidates:**
- Hundreds of applications with uncertain outcomes
- Limited visibility into genuine employer interest
- Increasing competition from automated applications
- Time wasted pursuing opportunities unlikely to materialize

**For employers:**
- Overwhelming application volumes
- Expensive and time-consuming screening
- Difficulty identifying candidates with genuine interest
- Strong candidates overlooked amid application congestion

Most platforms attempt to improve search, ranking, or screening. But better individual recommendations do not necessarily create a better overall hiring market.

## Our Solution

**What if, instead of helping everyone apply to more jobs, we could help everyone apply to fewer, better ones?**

Career Kitchen approaches hiring as a coordinated, two-sided matching system.

Our system combines:

1. **Global Allocation** — Optimize opportunities across candidates and employers rather than independently ranking candidates for each job.
2. **Reciprocal Matching** — Account for both candidate preferences and employer requirements.
3. **Budgeted Verification** — Prioritize uncertain predictions whose verification could meaningfully improve allocation decisions.
4. **Market Repair** — Reallocate opportunities when matches fail, preferences change, or positions are filled.
5. **Application Efficiency** — Reduce unnecessary interactions while preserving access to promising opportunities.

The objective is not simply to generate matches. It is to make the entire hiring process more efficient.

## How It Works

```text
Candidates + Employers
          |
          v
  Profile & Preference Analysis
          |
          v
  Reciprocal Compatibility Model
          |
          v
  Global Matching Optimization
          |
          v
  Budgeted Verification
          |
          v
  Curated Opportunities
          |
          v
  Employer & Candidate Decisions
          |
          v
  Local Market Repair
          |
          +----> Updated Allocation
```

Instead of allowing application volume to grow without coordination, Career Kitchen uses feedback from both sides to continually improve the allocation of opportunities.

## What Makes Career Kitchen Different?

| Traditional Job Platforms | Career Kitchen |
|---|---|
| Independent recommendations | Market-wide coordinated allocation |
| High application volume | Curated, limited opportunities |
| Primarily one-sided ranking | Reciprocal candidate-employer modeling |
| Reactive filtering | Proactive allocation |
| Independent matching decisions | Adaptive matching with market repair |

Career Kitchen is designed to complement existing hiring infrastructure while changing how candidates and opportunities are allocated.

## Our Technical Approach

At the core of Career Kitchen is an optimization framework that balances:

- Candidate-employer compatibility
- Mutual interest and acceptance likelihood
- Employer hiring requirements
- Candidate opportunity constraints
- Market congestion
- Uncertainty and verification costs
- Overall market efficiency

Our goal is to maximize successful, mutually beneficial matches under limited application and evaluation budgets.

Unlike a simple recommendation engine, the allocation model considers how assigning one opportunity affects the availability of others.

## Technology

Our planned architecture includes:

- **Frontend:** Next.js, React, Tailwind CSS
- **Backend:** Python, FastAPI
- **Optimization:** Google OR-Tools
- **Database & Authentication:** Supabase
- **Frontend Deployment:** Vercel
- **Backend Deployment:** Railway

*The implementation and deployment details will be updated as development progresses.*

## Evaluation

Career Kitchen is designed to be evaluated using measurable outcomes:

- Job fill rate
- Successful matches per application
- Applications required per successful hire
- Candidate and employer satisfaction
- Allocation efficiency
- Matching computation time
- Robustness to uncertain predictions

We aim to compare our matching architecture against independent ranking and sequential matching baselines under equivalent simulation conditions.

## Our Vision

**The best hiring platform should not be the one that generates the most applications. It should be the one that makes unnecessary applications obsolete.**

We envision a labor market where candidates spend less time applying, employers spend less time screening, and opportunities reach people who are genuinely well-suited and interested.

Career Kitchen is an experiment in making that future possible.

---

**Career Kitchen — Built at DubHacks 2026.**
