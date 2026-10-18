# ChamaPro dashboard

The loan officer's interface: record an interview, review the transcripts, run
the assessment and record a decision. React + TypeScript, built with Vite, no
UI framework. It talks only to the FastAPI backend in `src/chamapro/api/`.

## Running both servers

You need two terminals, both started from the project root.

**1. Backend** (port 8000). Loads the speech model once, which takes about a
minute on CPU.

```bash
source .venv/bin/activate
uvicorn chamapro.api.main:app --reload
```

Wait for `Application startup complete`.

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
npm run build      # type-checks (tsc) and builds into dist/
npm run lint       # oxlint
```

## Layout

```
src/
  api/          typed client (client.ts) and response types (types.ts, mirrors schemas.py)
  hooks/        useInterview (polls every 3 s while anything is transcribing),
                useQuestions, useRecorder (MediaRecorder, webm/Opus)
  lib/          routing (hash routes), risk meanings and the borderline rule,
                plain-language feature labels, domain labels, formatting
  components/   page shell, badges, notices and error boundary, replay button
  screens/      InterviewList, Recording, Review, Assessment
```

Routes: `#/` list · `#/interviews/:id/record/:n` · `#/interviews/:id/review` ·
`#/interviews/:id/assessment`.

## Behaviour worth knowing

- Every API error is shown with the server's own `detail` message. A rendering
  fault shows a reload notice instead of a blank page.
- Answers are transcribed one at a time, about 35 s each. While any answer is
  waiting or transcribing, the open screen polls every 3 s, and it stops when
  nothing is.
- Re-recording an answer that is being transcribed at that moment gets a 409
  with `Retry-After` from the server. The dashboard waits and retries by itself.
- Once assessed, an interview is read-only. The officer's decision is recorded
  once and cannot be changed.

Where the screens differ from the wireframes, and why, is listed in
[docs/design_changes.md](../docs/design_changes.md).
