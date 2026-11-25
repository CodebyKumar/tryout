# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- Primary audience of the public pages: people reviewing the owner's work (hiring managers, engineers) who open TryOut from a resume or portfolio. They have seconds, want to understand what it does, and try the demo.
- Recruiters who sign up, create roles, invite candidates and read reports.
- Candidates, who arrive by a private link and take a voice interview in the browser. No account.
- The owner, as admin: approves accounts, watches load and AI use.

## Product Purpose

An AI screening interviewer. A recruiter describes a role; TryOut drafts the interview plan and scoring rubric; each candidate talks with an AI interviewer from a private link; the recruiter gets a report and decides. Success: a reviewer understands the mechanism in one look and sees a real report in the demo.

## Positioning

Every rating in a report rests on a quote the candidate actually said, found in the transcript by code. The language model proposes; code decides section changes, time, follow-up limits, scores and the suggestion, and the report shows every turn's proposal and what code overrode.

## Operating Context

Recruiter workspace in a desktop browser; interview room in Chrome on a laptop (phones work in standard mode). Runs on free tiers (Groq, Supabase, Deepgram credit), so only a few interviews can run at once.

## Capabilities and Constraints

Roles from a job description, document or template; versioned briefs; candidates with scheduling windows and expiring links; invites opened in the recruiter's own Gmail or mail app with a calendar file; voice or typed interview; reports with verified quotes, resume fit, integrity signals, the candidate's rating, and a per-turn trace; decisions logged; strict integrity mode per role; admin approval of accounts; a read-only demo account with one real interview (simulated candidate). Vanilla HTML/CSS/JS, no build step.

## Brand Commitments

Name: TryOut. No Paytm or buildathon references. Logo: a mark plus wordmark (confirmed 2026-11-25). Voice: plain, specific, no hype.

## Evidence on Hand

The demo interview and its report (real AI, simulated candidate). No customers, testimonials, usage numbers or press exist; never invent them. The owner's portfolio-project status is not shown on the public pages (removed 2026-11-25).

## Product Principles

1. Show the evidence, not claims: every claim on a page names a feature that exists.
2. The human decides; the AI suggests.
3. Few words: a reviewer reads headings, not paragraphs.
4. Honest limits: say what integrity checks cannot see.
