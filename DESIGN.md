---
name: TryOut
description: An AI screening interviewer whose every score rests on a quote found in the transcript.
colors:
  cobalt: "oklch(52% 0.19 258)"
  cobalt-deep: "oklch(43% 0.2 262)"
  cobalt-soft: "oklch(76% 0.13 254)"
  cobalt-wash: "oklch(95% 0.028 256)"
  highlighter: "oklch(91% 0.1 95)"
  highlighter-ink: "oklch(25% 0.04 85)"
  paper: "oklch(99.3% 0.002 250)"
  surface: "oklch(99.9% 0.001 250)"
  paper-2: "oklch(96.2% 0.008 252)"
  paper-3: "oklch(93% 0.011 252)"
  rule: "oklch(90% 0.009 252)"
  rule-2: "oklch(83% 0.012 252)"
  ink: "oklch(21% 0.028 262)"
  ink-2: "oklch(36% 0.022 260)"
  muted: "oklch(50% 0.018 258)"
  on-dark: "oklch(98.6% 0.005 250)"
  graphite: "oklch(21% 0.024 262)"
  graphite-ink: "oklch(93% 0.010 250)"
  graphite-muted: "oklch(69% 0.022 256)"
  success: "oklch(50% 0.12 150)"
  warn: "oklch(55% 0.13 70)"
  error: "oklch(52% 0.19 27)"
typography:
  display:
    fontFamily: "Familjen Grotesk, system-ui, sans-serif"
    fontSize: "clamp(2.5rem, 5.4vw, 4.5rem)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Familjen Grotesk, system-ui, sans-serif"
    fontSize: "clamp(1.875rem, 3.4vw, 2.625rem)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Familjen Grotesk, system-ui, sans-serif"
    fontSize: "2.125rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.028em"
  section:
    fontFamily: "Familjen Grotesk, system-ui, sans-serif"
    fontSize: "1.3125rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.028em"
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.5
  body-public:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 500
    lineHeight: 1
  meta:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.45
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.9375rem"
    fontWeight: 500
    lineHeight: 1.4
    fontFeature: "tnum"
  figure:
    fontFamily: "Familjen Grotesk, system-ui, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
rounded:
  input: "6px"
  card: "8px"
  big-control: "10px"
  showcase: "16px"
  pill: "999px"
spacing:
  3xs: "2px"
  2xs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "40px"
  2xl: "64px"
  3xl: "96px"
components:
  button-default:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.input}"
    padding: "0 16px"
    height: "40px"
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-dark}"
    typography: "{typography.label}"
    rounded: "{rounded.input}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.ink-2}"
  button-primary-public:
    backgroundColor: "{colors.cobalt}"
    textColor: "{colors.on-dark}"
    rounded: "{rounded.big-control}"
    padding: "0 28px"
    height: "52px"
  button-primary-public-hover:
    backgroundColor: "{colors.cobalt-deep}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    padding: "0 12px"
    height: "40px"
  button-quiet-hover:
    backgroundColor: "{colors.paper-3}"
    textColor: "{colors.ink}"
  button-selected:
    backgroundColor: "{colors.cobalt-wash}"
    textColor: "{colors.cobalt-deep}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.input}"
    padding: "4px 12px"
    height: "40px"
  pill:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.input}"
    padding: "0 8px"
    height: "24px"
  pill-meets:
    backgroundColor: "{colors.cobalt-wash}"
    textColor: "{colors.cobalt-deep}"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "24px"
  showcase-panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.showcase}"
  appbar:
    backgroundColor: "{colors.paper}"
    height: "64px"
  evidence-mark:
    backgroundColor: "{colors.highlighter}"
    textColor: "{colors.highlighter-ink}"
---

# Design System: TryOut

## Overview

**Creative North Star: "The Marked Transcript"**

TryOut looks like a transcript someone has gone over with a highlighter: cool white paper, deep blue-black ink, hairline rules between rows, and exactly two signals laid on top. Cobalt says "act here" or "this is the measure"; highlighter yellow says "the candidate said this". Everything else stays quiet so those two marks carry the meaning, because the product's whole claim is that a score rests on something said.

The recruiter workspace, the admin page and the interview room are dense, flat and ruled: tables, ledgers and plan rows divided by 1px lines, panels with gently rounded 8px corners and no shadow. The public pages (home, sign in, sign up) use the same paper, ink and faces at a larger scale: an 18px body, a very large tight grotesk headline, and one lifted showcase panel that holds a real piece of the product. Motion is rare and earned: one highlighter sweep that triggers one score fill, shown in its end state under reduced motion.

**Key Characteristics:**
- Cool white paper, deep ink, one cobalt signal, highlighter yellow only on evidence.
- Familjen Grotesk set tight for heads and figures; IBM Plex Sans for reading; JetBrains Mono for timestamps.
- Ruled rows (1px) instead of boxes and shadows inside the workspace.
- Sentence case everywhere; no all-caps styling, no letter-spaced labels.
- The interface shows the real mechanism (transcript, plan bar, score bar) rather than illustrations of it.

## Colors

A near-monochrome cool palette with one saturated blue and one evidence yellow.

### Primary
- **Cobalt Signal** (cobalt): the one action and measure colour. Primary buttons on the public pages, the score bar fill, the interview timeline bar, the avatar, the selected-step marker, the level meter, focus rings, link hover underlines, the logo bubble.
- **Deep Cobalt** (cobalt-deep): hover for cobalt buttons, the score figure, text on cobalt-wash (the "Meets the bar" pill, a selected toggle).
- **Soft Cobalt** (cobalt-soft): alternate segments in the timeline bar only.
- **Cobalt Wash** (cobalt-wash): the score row behind a criterion, the guide band for new users, selected and "meets" tints.

### Secondary
- **Highlighter Yellow** (highlighter) with **Highlighter Ink** (highlighter-ink): the `<mark>` behind a quote the candidate actually said, in reports, transcripts and the home exchange; a 40% tint flashes a transcript line when a quote jumps to it; the second line of the logo mark is the same yellow, standing for the highlighted answer.

### Neutral
- **Cool Paper** (paper): page background, near white by owner request.
- **Surface** (surface): panels, inputs, menus, dialogs, the showcase panels.
- **Paper 2 / Paper 3** (paper-2, paper-3): table and exchange headers, pills, counts, skeletons, quiet-button hover.
- **Hairline / Strong Rule** (rule, rule-2): row dividers and panel borders; control borders.
- **Ink / Ink 2 / Muted** (ink, ink-2, muted): text in three steps; ink is also the workspace primary button fill.
- **On Dark** (on-dark): text on ink, cobalt, graphite and error fills.
- **Graphite** (graphite, graphite-ink, graphite-muted): the one dark band on the home page, video tiles and the camera preview, the interviewer caption sample.
- **Status** (success, warn, error): above-bar/advanced, hold/review, below-bar/rejected; always as text on a 10-14% tint of itself, never a solid fill (except the dialog-only destructive confirm).

### Named Rules
**The Two Signals Rule.** Cobalt means action or measure; highlighter yellow means a quoted thing the candidate said. Yellow never decorates, never marks a button, never fills a chart.

**The Tint Not Fill Rule.** Status badges are coloured text on a pale tint of the same hue. A solid status fill appears only on the destructive confirm inside a dialog.

## Typography

**Display Font:** Familjen Grotesk (with system-ui)
**Body Font:** IBM Plex Sans (with system-ui)
**Label/Mono Font:** JetBrains Mono (with ui-monospace), for timestamps, durations and transcript times only

**Character:** A compact, slightly quirky grotesk pulled tight for heads and numbers, over a sober, highly legible humanist sans for everything a recruiter reads. Mono is a ledger device, not a style.

### Hierarchy
- **Display** (700, clamp(2.5rem, 5.4vw, 4.5rem), 1): the home headline only, centred, about 17ch, two lines.
- **Headline** (700, clamp(1.875rem, 3.4vw, 2.625rem), 1.05): public section heads; the sign-in card title uses 700 2.25rem.
- **Title** (600, 34px, 1.15): workspace page titles.
- **Section** (600, 21px, 1.25): panel and dialog heads in the workspace.
- **Body** (400, 17px, 1.5): workspace body and table text; prose capped at 65-75ch.
- **Body public** (400, 18px, 1.55): public pages; the home deck runs 18-21px in ink-2.
- **Label** (500, 15px): buttons, form labels, nav links, table heads, pills.
- **Meta** (400, 13px): the smallest size in the system; hints inside menus, tooltips, tags.
- **Mono** (500, 15px, tabular): timestamps such as 00:46 and section times.
- **Figure** (Familjen 600, tabular): scores and counts; 26px in the workspace, 36px in the home score row.

### Named Rules
**The Sentence Case Rule.** No text-transform and no tracked-out labels anywhere. Labels are 15px weight 500 in ink-2 or muted.

**The Thirteen Floor Rule.** Nothing renders smaller than 13px.

## Layout

The workspace is a centred column (1200px max) under a sticky 64px top bar, with 40px side padding that drops to 16px under 60rem. Spacing follows one scale (2, 4, 8, 12, 16, 24, 40, 64, 96px); panels pad at 24px and stack 16px apart. Content is organised as ruled lists: tables, the plan (96px time column beside the question), the report ledger (72px column), each row divided by a hairline. Under 40rem, tables become one labelled card per row and two-column rows collapse to one.

The public pages sit in a 1160px column with a 76px top bar (mark plus wordmark left, Sign in and Try the demo right). The home hero is centred: headline, one deck line, two big actions, then the 920px exchange panel. Below it, three steps in a three-column grid topped by a 2px ink rule, one graphite band, a centred close, and a ruled footer. The sign-in and sign-up card is a single 460px column fixed at the same top position on both pages.

Breakpoints: 60rem (gutters shrink, grids go to one column) and 40rem (rows stack, buttons share width).

## Elevation & Depth

The workspace is flat: depth comes from tonal steps (paper, paper-2, surface) and 1px rules. Shadows appear only on things that float above the page, and on the public pages' showcase panels.

### Shadow Vocabulary
- **Pop** (`box-shadow: 0 16px 48px oklch(21% 0.028 262 / 0.18)`): dropdown menus and dialogs only.
- **Showcase lift** (`box-shadow: 0 30px 70px -36px oklch(30% 0.09 258 / 0.42), 0 2px 6px oklch(30% 0.05 258 / 0.06)`): the home exchange panel.
- **Card lift** (`box-shadow: 0 24px 60px -36px oklch(30% 0.09 258 / 0.35)`): the sign-in and sign-up card.

### Named Rules
**The Flat Workspace Rule.** Panels, tables and rows inside the app never cast shadows. A shadow means "this floats" (menu, dialog) or "this is the product on show" (public showcase).

## Shapes

Gentle, consistent rounding: 6px on controls, inputs, pills and menu items; 8px on panels, dialogs, menus and video tiles; 10px on the big public buttons and small showcase samples; 16px on the public showcase panels; full circles only for the avatar and the tooltip trigger. Bars (score bar, level meter) are fully rounded; the timeline bar is a single 6px-rounded strip of segments separated by 2px gaps. Borders are always 1px; the one heavier line is the 2px ink rule over each home step and the 2px underline on the active tab.

The logo mark is a cobalt speech bubble holding a white question line and a shorter yellow answer line; it sits at 30px beside the Familjen 600 wordmark.

## Components

### Buttons
- **Shape:** gently rounded (6px), 40px tall, 15px weight 500 label.
- **Default:** surface fill with a strong-rule border; hover darkens the border to muted; press nudges down 1px.
- **Primary (workspace, admin, room):** ink fill, on-dark text, hover to ink-2. One filled primary per screen.
- **Primary (public pages):** cobalt fill, hover to deep cobalt; the big size is 52px tall, 28px side padding, 10px radius.
- **Quiet:** transparent, ink-2 text, paper-3 on hover; used for Sign in, nav and the account menu trigger.
- **Selected toggle:** cobalt-wash fill, cobalt border, deep cobalt text.
- **Danger:** error text on default; the solid error fill exists only as a dialog's confirm.

### Chips / Pills
- **Style:** 24px tall, 6px radius, 15px weight 500 text on a pale tint: paper-2 neutral, cobalt-wash for meets or live, success, warn and error tints for their states.
- **Filters:** a paper-2 tray of 32px segments; the selected one turns surface with a 1px rule ring. Filter state lives in the URL.

### Cards / Containers
- **Corner Style:** 8px (workspace), 16px (public showcase).
- **Background:** surface on paper.
- **Shadow Strategy:** none in the workspace; see Elevation.
- **Border:** 1px rule.
- **Internal Padding:** 24px; the sign-in card 36px.

### Inputs / Fields
- **Style:** surface fill, 1px strong-rule border, 6px radius, 40px tall (48px on the auth card), 17px body text; labels sit above in 15px weight 500 ink-2.
- **Focus:** 2px cobalt outline pulled inside by 1px.
- **Error:** border turns error, with a 15px error line below the row.
- **Custom select:** a button that looks like the input and opens the shared dropdown with a tick on the chosen item; when open its border goes cobalt with a 3px cobalt-wash ring.

### Navigation
- **Top bar:** sticky 64px, 92% paper with an 8px backdrop blur and a bottom hairline. Logo left, main links as 40px quiet tabs (current page on paper-2), account menu right with a 28px cobalt initials avatar. Under 60rem the first name hides.
- **Dropdown:** one component for action menus, the account menu and selects. Surface, 1px rule, 8px radius, pop shadow, 4px inner padding, 6px-rounded items that tint paper-2 on hover and show an inset 2px cobalt ring on keyboard focus. Arrow keys, Home, End and Escape work; it flips upward when there is no room below and closes on scroll.
- **Tabs:** 44px tall, muted text, a 2px ink underline on the current tab.

### Tooltip
A 16px ring trigger in muted that shows an ink bubble (on-dark 13px text, 6px radius, 260px max) on hover or keyboard focus.

### Evidence Mark (signature)
The highlighter: yellow behind the exact quoted words, 2px radius, cloned across line breaks. On the home page it sweeps left to right (900ms, cubic-bezier(0.22, 1, 0.36, 1)), and only then does the score bar fill to its value (1100ms, starting at 950ms) and the "Quote found in the transcript" line appear. Reduced motion shows the finished state.

### Conversation Ledger (signature)
Transcript rows on a grid of mono timestamp (52px), speaker (104px, 15px weight 600) and text, each row ruled by a hairline. The score row below sits on cobalt-wash: criterion name and pill, a 10px rounded cobalt bar, and the figure as "7 / 10".

### Timeline Bar (signature)
The interview plan as one 8px strip, each section a segment sized by its minutes, alternating cobalt and soft cobalt, optional sections in strong rule.

## Do's and Don'ts

### Do:
- **Do** keep cobalt for actions and measures, and highlighter yellow for words the candidate said.
- **Do** separate rows with 1px rules and keep workspace panels flat at 8px radius.
- **Do** set timestamps and durations in JetBrains Mono with tabular figures, and scores in Familjen Grotesk 600.
- **Do** show a real piece of the product (a transcript row, the plan bar, a decision) where another site would use an illustration.
- **Do** give every motion a reduced-motion end state.
- **Do** use "-" as the separator in copy; never an em-dash.
- **Do** keep every claim on a page tied to a feature that exists.

### Don't:
- **Don't** use all-caps or letter-spaced labels anywhere.
- **Don't** put highlighter yellow on anything that is not quoted evidence (the logo's answer line is the only exception).
- **Don't** fill a status badge solid; tint it.
- **Don't** add shadows to workspace panels, tables or rows.
- **Don't** set anything below 13px.
- **Don't** use more than one filled primary button per workspace screen. The public pages repeat one cobalt action, Try the demo, in the bar, the hero and the close.
