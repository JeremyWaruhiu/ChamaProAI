# ChamaPro dashboard

The web app for everyone who uses ChamaPro:

- **Visitors:** a public landing page.
- **Loan officers:** start an interview for a member, record or type the
  answers, review the transcripts, read the assessment beside the SACCO's
  rule, and record a decision. They also manage applications, members and
  guarantors.
- **Administrators:** everything officers can do, plus an overview, users,
  the audit log and Model & Evaluation.
- **Members:** follow their own applications on a phone and add guarantors.

React + TypeScript, built with Vite. No UI framework; the one runtime
dependency beyond React is `motion`, for animation. It talks only to the
FastAPI backend in `src/chamapro/api/`.

Screenshots of the main screens are in
[docs/screenshots/](../docs/screenshots/). They were taken against a temporary
database seeded with `scripts/seed_demo.py`, and every person shown is
fictional.

## Running both servers

You need two terminals, both started from the project root.

**1. Backend** (port 8000). Loads the speech model once, which takes about a
minute on CPU.

```bash
source .venv/bin/activate
uvicorn chamapro.api.main:app --reload --reload-dir src --reload-dir scripts
```

Wait for `Application startup complete`. Keep both `--reload-dir` flags.
Without them, loading the speech model writes into `.hf_cache/`, the reloader
sees it and restarts, and the server loops forever without answering.

**2. Dashboard** (port 5173).

```bash
cd frontend
npm install        # first time only
npm run dev
```

Open http://localhost:5173. The dev server forwards every `/api` request to
http://localhost:8000, so the browser sees one site and no CORS is involved.

To use a laptop's microphone, open the dashboard on `localhost`. Browsers only
allow the microphone on `localhost` or HTTPS, so a tablet on the branch network
needs HTTPS (for now, use **Upload a recording** there).

## Checks

```bash
npm test           # Vitest: role-based routing, wizard, guarantor form, decision panel,
                   # comparator states, reduced motion, borderline rule, labels, timeouts
npm run lint       # oxlint
npm run build      # type-checks (tsc) and builds into dist/
```

CI runs all three on every push and pull request to `main`. Most tests render
to static markup in Node. The few that click through a screen (the wizard, the
guarantor form, the layout) run in jsdom; those files start with
`// @vitest-environment jsdom`.

## Layout

```
src/
  strings.ts    every string the interface shows (see "Translation" below)
  index.css     design tokens (colour, type, spacing, radius, shadow, motion) and shared classes
  api/          typed client (client.ts) and response types (types.ts, mirrors schemas.py)
  hooks/        useInterview (polls every 3 s while anything is transcribing), useQuestions,
                useRecorder (MediaRecorder plus a live input level), useLoad, useHealth
  lib/          routing and role access (router, auth); motion presets and reduced motion;
                wizard, guarantor, decision and form validation; application statuses and
                the member's timeline; risk meanings and the borderline rule; feature,
                topic and fact labels; formatting
  components/   layouts (staff sidebar and top bar; member portal), ui (badge, card, KPI,
                stepper, timeline, field, modal, skeletons, empty state), toasts, icons,
                interview shell, notices and error boundary, charts, replay button,
                landing illustration
  screens/      one file per screen; each loads as its own chunk
```

## Routes

| Route | Screen | Who |
|---|---|---|
| `#/` | Landing page | everyone |
| `#/login` | Sign in (password, and Google when configured) | everyone |
| `#/profile` | Your profile, change password, sign out everywhere | every role |
| `#/app` | Officer home | officers, admins |
| `#/app/start[?member=id]` | Start-interview wizard | officers, admins |
| `#/interviews` | All interviews | officers, admins |
| `#/interviews/:id/record[/:n]` | Interview runner, question n (else the first unanswered) | officers, admins |
| `#/interviews/:id/review` | Transcript review | officers, admins |
| `#/interviews/:id/assessment` | Assessment and decision | officers, admins |
| `#/applications[?status=s]`, `#/applications/:id` | Applications, one application | officers, admins |
| `#/members`, `#/members/:id` | Members, one member | officers, admins |
| `#/admin`, `#/admin/users`, `#/admin/audit`, `#/admin/results` | Overview, users, audit log, Model & Evaluation | admins |
| `#/my`, `#/my/applications/:id` | Member portal | members |

The access rules are in `lib/auth.ts` and match the server's. If you open a
route your role cannot use, you go to your role's home instead: officers to
`#/app`, admins to `#/admin`, members to `#/my`. If you are signed out, you go
to the sign-in page, and it brings you back to that route afterwards.

## Design

- **Tokens.** Colours, the type scale, spacing, radii, shadows and motion
  durations are tokens in `index.css`. Components use the tokens, never raw
  values.
- **Contrast.** Text meets WCAG AA. The focus ring is a 3 px clay outline, and
  a light gold one on the dark sidebar.
- **Fonts.** System fonts only (a serif for headings, a sans for text), so
  nothing is fetched from the internet.
- **Motion.** The `motion` library animates entrances and state changes only.
  Under `prefers-reduced-motion`, nothing moves: the presets in `lib/motion.ts`
  do nothing, `MotionConfig` follows the user's setting, and the CSS turns off
  every animation and transition.
- **Slow connections.** There are no images except inline SVG. Each route is
  its own chunk. The JavaScript loaded on first visit is about 130 KB gzipped.
- **Phones.** The member portal is designed for phones first. Every screen
  works at 390 px wide without scrolling sideways.

## Translation

Every string the interface shows lives in `src/strings.ts`, in one object.
Text containing numbers or names is written as a function, so the whole
sentence can be translated rather than pieced together. To add Kikuyu, write
a second object of the same type (`Strings`) and export it as `t`.

The exception is text the server sends: error details, the member's status
labels and the reasons shown to members. Those are shown exactly as received.

## Behaviour worth knowing

- No request waits more than 15 seconds (the assessment, which takes about
  30 s, gets 90 s). A request that runs out of time shows an error with a
  **Retry** button, so no screen spins forever.
- Every API error is shown with the server's own `detail` message. A rendering
  fault shows a reload notice instead of a blank page.
- Answers are transcribed one at a time, about 35 s each. While any answer is
  waiting or transcribing, the open screen polls every 3 s, and it stops when
  nothing is.
- Re-recording an answer that is being transcribed at that moment gets a 409
  with `Retry-After` from the server. The dashboard waits and retries by itself.
- Once assessed, an interview is read-only. The officer's decision is recorded
  once and cannot be changed.
- The wizard creates the member (if new), then the interview, then the loan
  application. If a step fails, Retry carries on from that step, so nothing is
  created twice.
- Practice interviews and applications carry a Practice badge on every screen
  they appear on, the member portal included.
- A member's screens never show probabilities, the risk band, SHAP values or
  officer notes. The server does not send them to members in the first place.

Where the screens differ from the wireframes, and why, is listed in
[docs/design_changes.md](../docs/design_changes.md).
