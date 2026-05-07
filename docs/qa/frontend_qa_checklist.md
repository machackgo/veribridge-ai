# VeriBridge AI — Frontend QA Checklist

> Run these checks after each deploy or major change.  
> Automated Playwright tests cover most of these. This checklist is for manual spot-checking.

---

## Setup

```bash
# Install browsers (one-time, ~300 MB)
npx playwright install chromium

# Run automated tests
npm --prefix apps/web run test:e2e

# Or run with UI
npm --prefix apps/web run test:e2e:ui

# Dev server for manual testing
npm --prefix apps/web run dev
# → open http://localhost:3000
```

---

## Landing page `/`

### Navbar
- [ ] VeriBridge AI logo → navigates to `/`
- [ ] Platform → scrolls to `#platform`
- [ ] Students → navigates to `/dashboard`
- [ ] Recruiters → navigates to `/recruiter`
- [ ] Universities → navigates to `/university`
- [ ] Roadmap → scrolls to `#roadmap` / `#workflow`
- [ ] Sign in → navigates to `/dashboard`
- [ ] **Start Building Profile →** navigates to `/dashboard`

### Hero section
- [ ] **Start Building Profile →** button has white text on dark background (visible)
- [ ] **View Platform** button has visible text
- [ ] Both hero CTAs navigate correctly (see above)

### Three-sided platform cards (below `#platform`)
- [ ] "Preview the students dashboard →" → `/dashboard`
- [ ] "Preview the recruiters dashboard →" → `/recruiter`
- [ ] "Preview the universities dashboard →" → `/university`
- [ ] All three cards have visible "Preview" links

### Visa Intelligence section (`#visa`)
- [ ] **Check Visa Fit →** → `/dashboard/visa-fit`
- [ ] **View compatible jobs** → `/dashboard/jobs`
- [ ] **Learn privacy controls** → `/dashboard/privacy`
- [ ] Visa job rows are clickable → `/dashboard/jobs`
- [ ] Legal disclaimer is visible

### Proof-of-Skill section (`#proof`)
- [ ] **Docker** tab: selected by default (`aria-selected="true"`)
- [ ] **Docker** → evidence panel shows "Docker" heading + 4 sources
- [ ] **React & TypeScript** tab: click → evidence panel updates to React evidence
- [ ] **Distributed Systems** tab: click → panel updates to DS evidence
- [ ] **Machine Learning** tab: click → panel shows "Pending" badge (not Verified)
- [ ] **SQL & Postgres** tab: click → panel shows 2 evidence sources
- [ ] GitHub Repo evidence cards: open `https://github.com/` in new tab
- [ ] Deployed App evidence cards: open `https://example.com/` in new tab
- [ ] Coursework evidence cards: navigate to `/dashboard/profile`
- [ ] Certification evidence cards: navigate to `/dashboard/profile`
- [ ] All evidence card text is readable (not invisible/zero-contrast)

### Final CTA section
- [ ] **Start Building Profile →** has white text on dark card → `/dashboard`
- [ ] **View Roadmap** ghost button has visible text

### Footer
- [ ] VeriBridge AI logo → `/`
- [ ] Platform → `#platform`
- [ ] Students → `/dashboard`
- [ ] Recruiters → `/recruiter`
- [ ] Universities → `/university`
- [ ] Privacy → `/dashboard/privacy`

---

## Student dashboard `/dashboard`

### Sidebar
- [ ] All 7 workspace items visible: Overview · Profile & Proof · Job Matches · Applications · Skill Gaps · **Visa Fit** · Mock Interview
- [ ] Account items visible: Settings · Privacy
- [ ] Active page item has **dark navy background + white text** (not dark text on dark bg)
- [ ] Inactive items have dark text on white background
- [ ] Hover items show subtle light background
- [ ] **Visa Fit** is present and links to `/dashboard/visa-fit`

### Overview content
- [ ] Score card visible (dark gradient, ring score)
- [ ] Visa Fit summary strip visible (5 cells: Status, CPT, OPT, STEM OPT, Top Visa Match)
- [ ] Job match cards show **both Match% and Visa%** columns
- [ ] Low visa fit (Anthropic 46%) shows amber color
- [ ] "Full details →" link on Visa strip → `/dashboard/visa-fit`

### Routes
- [ ] `/dashboard` → renders
- [ ] `/dashboard/profile` → renders "Your verified profile"
- [ ] `/dashboard/jobs` → renders "Roles ranked for you"
- [ ] `/dashboard/applications` → renders "Application tracker"
- [ ] `/dashboard/skill-gaps` → renders "Close the gaps"
- [ ] `/dashboard/visa-fit` → renders Visa intelligence heading
- [ ] `/dashboard/mock-interview` → renders "Practice with the AI interviewer"
- [ ] `/dashboard/settings` → renders "Settings"
- [ ] `/dashboard/privacy` → renders "You control what's visible"

---

## Recruiter dashboard `/recruiter`

### Sidebar
- [ ] Search (active on /recruiter) with count badge `240`
- [ ] Saved Lists with count badge `8`
- [ ] Pipeline with count badge `42`
- [ ] Messages with count badge `12`
- [ ] Job Posts with count badge `5`
- [ ] Insights section: Funnel · Trust score
- [ ] Account section: Team & billing
- [ ] Active item: dark navy bg + **white text**
- [ ] Count badges: dark text on light bg (inactive), white text on semi-transparent bg (active)

### Routes
- [ ] `/recruiter` → renders candidate search
- [ ] `/recruiter/search` → renders
- [ ] `/recruiter/candidates` → renders
- [ ] `/recruiter/invites` → renders
- [ ] `/recruiter/company` → renders
- [ ] `/recruiter/settings` → renders

---

## University dashboard `/university`

### Sidebar
- [ ] Overview (active on /university)
- [ ] Readiness
- [ ] Skill gaps
- [ ] Outcomes
- [ ] Employer trends
- [ ] Cohort compare
- [ ] Reports section: Quarterly export · Department brief
- [ ] Account section: Privacy & DPA · Settings
- [ ] Active item: dark navy bg + white text

### Content
- [ ] K-anon banner visible (green gradient)
- [ ] 5-column metric strip (Cohort size, Avg readiness, Verified profiles, Placed, Employer engagement)
- [ ] Readiness bar chart visible with 8 months
- [ ] Skill gap heatmap with colored cells

### Routes
- [ ] `/university` → renders "Class of 2026 · Cohort overview"
- [ ] `/university/analytics` → renders
- [ ] `/university/skill-gaps` → renders
- [ ] `/university/outcomes` → renders
- [ ] `/university/employers` → renders
- [ ] `/university/privacy` → renders

---

## Button contrast check

All dark (navy/black) buttons must have white text. Run this in browser console:

```js
document.querySelectorAll('button, a').forEach(el => {
  const bg = getComputedStyle(el).backgroundColor;
  const color = getComputedStyle(el).color;
  if (bg.includes('rgb(10, 14, 26)') || bg.includes('#0a0e1a')) {
    console.log('Dark button:', el.textContent?.trim(), '| color:', color);
  }
});
```

Expected: all dark buttons show `rgb(255, 255, 255)` as text color.

---

## Accessibility quick checks

- [ ] All interactive elements reachable by Tab key
- [ ] Skill tabs have `role="tab"` and `aria-selected`
- [ ] Evidence panel has `role="tabpanel"`
- [ ] Sidebar nav links have `aria-current="page"` when active
- [ ] All images have `alt` attributes
- [ ] Color contrast meets WCAG AA for primary text

---

## Running Playwright tests

```bash
# Install browsers first (required once)
cd apps/web && npx playwright install chromium

# Run all e2e tests
npm --prefix apps/web run test:e2e

# View HTML report
npx --prefix apps/web playwright show-report
```

Test files:
- `e2e/navigation.spec.ts` — navbar, hero, visa section, platform cards
- `e2e/proof-section.spec.ts` — proof-of-skill tab switching and evidence card links
- `e2e/dashboards.spec.ts` — all sidebar links, heading checks, key routes, toggle interactions

---

## Dead UI / Clickability Audit

### Toggle switches

#### Student dashboard
- [ ] `/dashboard/settings` — Notification toggles: "New high-match jobs", "Recruiter views your profile", "Application status updates", "Weekly progress report" — each click flips `aria-checked` and shows a DemoToast
- [ ] `/dashboard/privacy` — Recruiter discovery toggles: "Discoverable in search", "Show real name", "Show GPA" — each click flips state and shows toast
- [ ] `/dashboard/privacy` — Visa disclosure toggles: "Show F-1 status to F-1-OK employers", "Show F-1 status to all employers" — interactive
- [ ] `/dashboard/privacy` — Skill evidence toggles: "Public GitHub repos", "Coursework / transcripts", "Live deployed projects", "Certifications" — interactive
- [ ] `/dashboard/visa-fit` — Visa visibility toggles on each job card — flip state and show toast

#### Recruiter dashboard
- [ ] `/recruiter/settings` — Search defaults section: 3 toggles all respond to click
- [ ] `/recruiter/settings` — Invite preferences section: 3 toggles all respond to click
- [ ] `/recruiter/settings` — Notifications section: 3 toggles all respond to click (Pipeline follow-ups starts OFF)
- [ ] All toggles show DemoToast with label + enabled/disabled state

#### University dashboard
- [ ] `/university/privacy` — Privacy controls section: 6 toggles all respond to click (all start ON)
- [ ] All toggles show DemoToast with label + enabled/disabled state

### CTA buttons — Student dashboard

- [ ] `/dashboard` (Overview) — "Open project brief →" button → toast: "Project brief — AI-generated plan coming soon."
- [ ] `/dashboard/profile` — "Preview as recruiter" button → toast: "Preview mode — recruiter view coming soon."
- [ ] `/dashboard/profile` — "Edit profile" button → toast: "Edit profile — coming soon."
- [ ] `/dashboard/profile` — "View Evidence →" buttons on each artifact → toast: "Evidence viewer — coming soon."
- [ ] `/dashboard/jobs` — "Save" button on each job row → toast: "Job saved to your list (demo)."
- [ ] `/dashboard/jobs` — "Prepare app →" button on each job row → toast: "Preparing tailored application — backend coming soon."
- [ ] `/dashboard/skill-gaps` — "Open project brief →" button → toast: "Project brief — AI-generated plan coming soon."
- [ ] `/dashboard/mock-interview` — "▶ Start mock interview · ~45 min" button → toast with demo message
- [ ] `/dashboard/settings` — Account buttons (Connected accounts, 2FA, Change password, Deactivate) → each shows toast
- [ ] `/dashboard/privacy` — Data & consent buttons (Download, Consent log, Manage, Audit log, Delete) → each shows toast

### CTA buttons — Recruiter dashboard

- [ ] `/recruiter` (Overview) — "↓ Export" button → toast: "Export feature coming soon — backend integration required."
- [ ] `/recruiter` (Overview) — "+ New job post" button → toast: "Job post creation coming soon."
- [ ] `/recruiter` (Overview) — "Search" button → toast: "Search is demo mode — results shown above."
- [ ] `/recruiter` (Overview) — "Save" on candidate preview → toast: "Candidate saved to your lists (demo)."
- [ ] `/recruiter` (Overview) — "Send invite →" on candidate preview → toast: "Invite sent — backend integration coming soon."
- [ ] `/recruiter/search` — "+ Add candidate" button → toast
- [ ] `/recruiter/candidates` — "+ New list" button → toast
- [ ] `/recruiter/invites` — "+ New message" button → toast
- [ ] `/recruiter/invites` — "Send" reply button → toast
- [ ] `/recruiter/company` — "+ New job post" button → toast
- [ ] `/recruiter/settings` — All 9 toggle switches respond + show toast

### CTA buttons — University dashboard

- [ ] `/university` (Overview) — "↓ Export PDF report" button → toast: "Report export — PDF generation coming soon."
- [ ] `/university/analytics` — "↓ Export" button → toast: "Export coming soon."
- [ ] `/university/skill-gaps` — "↓ Export" button → toast: "Export coming soon."
- [ ] `/university/outcomes` — "↓ Quarterly export" and "↓ Department brief" buttons → each shows toast
- [ ] `/university/employers` — "↓ Export" button → toast: "Export coming soon."
- [ ] `/university/employers` — Employer action buttons (4 items) → each shows toast: "Action queued — backend integration coming soon."
- [ ] `/university/privacy` — 6 toggle switches all respond + show toast

### DemoToast verification

- [ ] Toast appears within 200ms of button click
- [ ] Toast has `role="status"` and `aria-live="polite"` for screen reader support
- [ ] Toast shows green checkmark (✓) prefix
- [ ] Toast auto-dismisses after 2500ms
- [ ] Toast displays correct message for each action
- [ ] Toast is fixed bottom-right (z-index 9999), does not overlap interactive content
- [ ] Multiple rapid clicks only show the latest toast (state reset on each click)

### Sidebar links (already covered by Playwright, verify manually)

- [ ] All student sidebar links navigate to correct routes
- [ ] All recruiter sidebar links navigate to correct routes
- [ ] All university sidebar links navigate to correct routes
- [ ] Active page item is highlighted correctly

### Disabled / coming-soon states

- [ ] All "coming soon" toasts clearly communicate the feature is not yet wired to a backend
- [ ] No button click results in a 404 or broken navigation
- [ ] `readOnly` inputs on search bars do not throw errors when clicked
- [ ] Form submission is prevented on all buttons (all have `type="button"`)

### Accessibility

- [ ] All toggle buttons have `role="switch"` and `aria-checked` attribute
- [ ] `aria-checked` reflects the actual current state (not just the initial state)
- [ ] All toggle buttons have `aria-label` matching the toggle's label text
- [ ] DemoToast has `role="status"` and `aria-live="polite"`
- [ ] All `<button>` elements have explicit `type="button"` to prevent form submission
