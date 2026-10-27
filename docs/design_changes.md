# Design changes: dashboard vs wireframes (Figures 4.8–4.12)

The dashboard (`frontend/`) follows the wireframes in
`docs/wireframes/` for screen structure and flow. This file records every
place where it differs, whether something was added, changed or deferred, with
a one-line reason. Wireframe figure numbers refer to Chapter 4.

## Across all screens

| Change | Status | Reason |
|---|---|---|
| Interview screens share a step bar (Record answers · Review transcripts · Assessment) and a back link to the interview's loan application (or to all interviews) | Added | The wireframes show the screens separately; officers need a visible, one-tap way between the three steps of one interview. |
| Risk classes use colour (green / amber / red) as well as text | Changed | The wireframes are monochrome; colour speeds recognition, and the text label means it never relies on colour alone. |
| System fonts only, no web fonts | Changed | Rural branches may be offline or on slow links; nothing is fetched from the internet. Headings use the system serif (Iowan, Palatino, Georgia), body text the system sans. |
| Status words are plain language ("Waiting", "Transcribing", "Transcribed", "Not transcribed") | Changed | Officers have basic computer literacy; "queued" and "failed" are system terms. |
| Interview questions grouped by the eight domains recorded in `data/manifest.csv`, not Table 3.1's domains | Changed | The 40 recorded responses use the manifest's domains (Household, Chama, …); Table 3.1's set (Social Capital, Character & Attitude) has no recordings. Applies to question set v1; v2 has one topic per question. |
| Question set v2: eight questions, one per topic, each targeting named classifier features; age, sex, education and marital status move to an applicant form | Changed | The 40-sentence draft asked many things the classifier never uses and left some features to chance. Form plus v2 cover the 40 features exactly once (tested). v1 is kept so the recorded Kikuyu demo and the evaluation still load. |
| Practice interviews: a banner on every screen of the interview, the decision labelled practice, excluded from live statistics | Added | Officers need to rehearse on the real screens without a training run counting as a lending decision or skewing the figures on Model & Evaluation. |
| English interviews (interview language Kikuyu or English) | Added | Some applicants prefer English. English answers are transcribed by the English Whisper model and are not translated. |
| A request that gets no answer within 15 seconds (90 s for the assessment) shows an error with a Retry button | Added | The wireframes show no failure states; a stalled server must never leave a screen spinning forever. |

## Figure 4.8 — Login

| Change | Status | Reason |
|---|---|---|
| No login screen, no officer name in the header | Deferred (Sprint III) → **Implemented** | Authentication and role separation are now in place: a sign-in page at `#/login`, cookie sessions (8 h), officer, admin and member roles, and the signed-in user with a role badge in the top bar's account menu (Your profile, Sign out). Each role lands on its own home; a member cannot open any staff screen and an officer cannot open the admin screens. |
| Username instead of email | Changed | Accounts are created by the SACCO administrator with `scripts/create_user.py`; officers need not have an email address, and none is stored. |
| Show / hide password toggle | Added | Typing a password on a tablet keyboard is error-prone; letting the officer check it avoids lockouts. |
| "Forgot password?" → "Accounts are created by your SACCO administrator." | Changed | There is no email or self-service reset; the administrator resets accounts. A link that led nowhere would mislead. |
| Five failed sign-ins for one username in 15 minutes lock it for the rest of the window | Added | Limits password guessing against a shared branch server. |
| "Sign in with Google" button under the password form, after an "or" divider | Added | Optional, shown only when `GOOGLE_CLIENT_ID` is set. Signs in only users who already exist and have that Google email linked (`scripts/link_google.py`); it never creates an account. Google's own rendered button is used, per its branding guidelines. Password sign-in stays, since officers may have no Google account and branches may be offline. This is the one place the dashboard loads anything from the internet, and only when configured. |
| Branch selection | Deferred (Sprint III) | There is one register for now; branches need their own data separation, not only a menu. |

## Figure 4.9 — Applicant dashboard → Interviews list

| Change | Status | Reason |
|---|---|---|
| Lists interviews, not an applicant register | Changed | There are no applicant records beyond a name until registration exists; an interview is the unit an officer works on. |
| Columns: applicant, date, answers recorded out of the interview's question count, status, risk class | Changed | Specified for Sprint II; shows recording progress, which the wireframe's single badge could not. |
| "English" and "Practice" tags under the applicant's name; a practice decision reads "Practice decision: …" | Added | The two options change how an interview is handled; they must be visible before it is opened. |
| "PROCESSING" badge replaced by a status column ("Transcribing answers", "Ready for review", "Decision: …") | Changed | Status and risk class are different facts; mixing them in one badge hid which step an interview is at. |
| Officer's decision shown in the status column | Added | The list should show whether a decision has been recorded, not only the model's class. |
| Opening an interview goes to its next step (record, review or assessment) | Added | Saves the officer finding where they left off. |
| Search by name or member number | Deferred → **Implemented** | The top bar searches members (by name or member number, on the server) and applications; the Applications, Members and Interviews tables each have their own search and filters. |
| Member numbers (M-0412) | Deferred → **Implemented** | A member register (`members`: member number, name, phone, membership start) with loan applications linked to it, and Members and Applications screens over it. No national ID number is stored (data minimisation, Kenya Data Protection Act 2019). |
| Pagination | Deferred | Not needed at Sprint II volumes. |
| New interview → a start-interview wizard: member (find or add), loan details, applicant form (age, sex, highest education, marital status), language and mode, then a check-and-begin step | Added → Changed | The wireframe shows the button but not what follows. Starting an interview now also creates the member's loan application, so the SACCO rule can be checked. The four applicant facts are entered here rather than asked in the interview, in the exact categories the classifier was trained on, served by `GET /api/applicant-form` so the form and the model cannot drift apart. Each step is validated before the next; a retry never creates the member, interview or application twice. |

## Figure 4.10 — Interview recording

| Change | Status | Reason |
|---|---|---|
| One question per screen with Previous / Next | Kept | As in the wireframe. |
| Kikuyu question text with English gloss beneath | Kept, with fallback | The Kikuyu wording is still being corrected by a native speaker; where it is missing the English is shown alone. English interviews show the English only. v2 has no Kikuyu wording yet. |
| Questions are a draft (`docs/interview_questions.txt`) | Changed | No 40-question instrument existed; one question per scripted answer was drafted from Table 3.1's wording, pending review. This is question set v1; new interviews use the eight-question v2 in `questions.json`. |
| **Type the answer** beside Record and Upload | Added | Lets the officer enter an answer when recording is impossible or the applicant prefers to write; a typed answer skips transcription and is ready for review at once. |
| v2 progress shows "Question n of 8", a progress bar, and one status chip per question (not answered, waiting, transcribed, failed) instead of domain segments | Changed | With one question per topic, domain segments would repeat the question chips. v1 keeps the eight domain segments. Opening an interview resumes at its first unanswered question, and says so. |
| Record answer, Stop, Replay, Re-record | Kept | As in the wireframe; Replay plays the stored clip from the server. |
| Upload a recording | Added | Specified; lets an officer use a phone recording when the laptop microphone fails. |
| Live status badge per answer (Waiting, Transcribing, Transcribed, Not transcribed) with a calm waiting message and estimate | Added | Transcription takes about 35 s per clip on CPU; the officer must see that waiting is normal and can carry on. |
| Re-record while transcribing waits and retries automatically | Added | The server refuses to delete a clip mid-transcription (409, Retry-After); the dashboard waits rather than showing an error. |
| Domain progress segments are tappable; question number buttons for the current domain | Added | Lets the officer return to any answer without stepping through every screen. |
| Live waveform | Changed | A live level meter (twenty segments, from the microphone's input level) shows that sound is being picked up; a full waveform is still not drawn. |
| Audio quality indicator | Deferred | Needs signal analysis that is not part of the pipeline yet. |
| Save draft | Deferred | Every answer is saved to the server as soon as it is recorded, so there is no draft to keep. |
| Offline buffering ("uploads when a connection is available") | Deferred | Needs a service worker and local storage of personal audio; a separate piece of work. |
| Recording from a tablet's microphone on the branch network | Deferred (Sprint III, deployment) | Browsers allow the microphone only on `localhost` or HTTPS. The dashboard is served over plain HTTP in Sprint II, so only the laptop running it can record; a tablet must use **Upload a recording**. Serving it over HTTPS (a certificate on the branch server) is a Sprint III deployment item. |

## Figure 4.11 — Transcript review

| Change | Status | Reason |
|---|---|---|
| All answers listed one per card, instead of one transcript with a timeline player | Changed | Specified: every transcribed response, its question, and an editable Kikuyu transcript. |
| One-sentence instruction at the top | Added | Specified; tells the officer what to do before assessing. |
| "Edit transcript" → transcript is always editable, with Save correction and Undo | Changed | Removes a step on a touchscreen. |
| Edited answers marked "Edited", with the speech model's original text and the time of correction | Added | Specified; the original is kept for audit. |
| A failed or empty transcript can be typed in by the officer | Added | Otherwise that answer would be lost to the assessment. |
| Typed answers marked "Typed", with no Replay | Added | There is no recording; the mark tells a reviewer the text was entered by hand, not heard by the model. |
| Synchronised playback bar | Changed | Replaced by a Replay button per answer; each answer is a separate 3–10 s clip. |
| Shaded low-confidence spans and the "ASR confidence" figure | Deferred | The ASR stage does not produce per-word confidence yet. |
| Flag for supervisor | Deferred | Officer and admin roles now exist; the flag itself and a supervisor's queue are still to be built. |
| "Confirm and extract features" → "Run assessment", with a confirmation step | Changed | One plain action; the confirmation is there because an assessment can never be changed afterwards. |
| Run assessment disabled until nothing is waiting or transcribing, and until corrections are saved | Added | Specified for transcription; unsaved corrections would otherwise be silently left out. |
| Read-only once assessed | Added | Specified; assessments are immutable. |

## Figure 4.12 — Credit assessment

Also added beside the risk band: a plain-language explanation (the strongest facts in the applicant's favour and against, from the SHAP values), and the transcripts with their recordings in a collapsible section, for a last check before deciding.

| Change | Status | Reason |
|---|---|---|
| Risk class shown large with its operational meaning (Low = approve on standard terms; Medium = refer to the loan committee; High = decline or refer for manual review) | Changed | Specified; tells the officer what the class means at the SACCO. |
| "confidence 0.84" → "Model probability" plus bars for all three classes | Changed | Specified; a close call has to look like a close call. |
| Borderline banner when the top two classes are within 10 points | Added | Specified; overrides the class shown with a referral. |
| Evidence completeness with a warning below 80% | Changed | Moved out of the evidence footnote into its own panel, so a thin assessment is noticed. |
| SHAP bar chart → plain-language rows, each with a small bar | Changed | Officers need "Monthly income — KSh 8,000" rather than feature codes. |
| Contribution wording "made Medium risk more / less likely" instead of "raised the assessment" | Changed | SHAP values are relative to the predicted class, so "raised" would be ambiguous for a risk score. |
| Extracted facts listed field by field, with the facts not stated | Changed | Shows exactly what the system heard and what it did not. |
| Fixed notice "Decision support only. The loan officer makes the decision." | Changed | Replaces the wireframe's advisory footnote; specified wording, shown at the top. |
| Approve / Decline / Refer recorded as the officer's decision, separate from the model's assessment, shown side by side | Changed | The model recommends, the officer decides; the decision is stored once and cannot be changed. |
| Decision buttons have equal weight; nothing is preselected | Changed | The wireframe made Approve the primary button, which nudges the officer. |
| A note can be recorded with the decision; a confirmation step precedes it | Added | Records why; the decision is permanent. |
| The decision is marked when it differs from the model's recommendation | Added | Makes overrides visible for later review without implying the officer was wrong. |
| One audit line under each assessment: assessment id, time, who assessed it, classifier file and SHA-256, extraction model, "stored permanently" | Added | Auditability (Chapter 4): the stored record identifies exactly which model produced it and who ran it; the line is small and at the foot of the screen, so it does not compete with the decision. |
| Facts entered on the applicant form listed apart from "What the system heard" | Added | They were typed by the officer, not extracted from speech; listing them as heard, or as "not stated", would misdescribe them. |
| A practice interview's decision panel and recorded decision say "practice" | Added | A practice decision must never be mistaken for a lending decision. |
| Approve at a reduced amount | Deferred → **Implemented** | The decision panel offers five outcomes: approve, approve with guarantors (the officer sets how many, 1 to 10, default 2), approve a reduced amount (below the request), refer, decline; plus officer notes (staff only) and a plain-language message for the member. The two application-only outcomes are disabled, with a reason, on an interview without a loan application. |
| Loan amount requested in the header | Deferred → **Implemented** | Captured on the loan application (amount, purpose, term, SACCO savings) in the wizard; shown on the application screen and in the decision panel. |
| SACCO baseline (savings multiplier) and divergence panel | Deferred → **Implemented** | "Model and SACCO rule, side by side": the model's recommendation beside the rule's (Chapter 5: up to 3 x savings, 2 guarantors, 6 months' membership), each condition shown pass / fail / pending with whether it agrees with the model. Computed live, never stored with the assessment. |
| Export report | Deferred | Not needed for Sprint II; the assessment is stored and viewable. |
| Storing the repayment outcome for retraining | Deferred | Needs loan servicing data after disbursement. |

## Part C: redesign, member portal and administration screens

| Change | Status | Reason |
|---|---|---|
| One design-token system (`frontend/src/index.css`): warm neutrals, forest green, clay and ochre accents, type scale, spacing, radius, shadow, motion durations; shared components for every screen | Changed | A financial product for SACCOs should look calm and trustworthy, and consistent from screen to screen. The wireframes' pale-green palette is kept as the brand colour. |
| Public landing page at `#/` (how it works, for SACCOs, for members, privacy and "the officer always decides") | Added | People arriving at the system need to know what it does and that a person decides. It has no statistics, testimonials or partner logos: none exist. The illustration uses a fictional applicant and draws the Kikuyu transcript as lines, since no Kikuyu text has been written for v2 yet. |
| Staff layout: collapsible sidebar (a drawer on small screens), top bar with search, account menu and role badge; a prominent Start interview | Changed | Replaces the per-screen green header now that there are ten staff screens. |
| Officer home: today's interviews, interviews in progress, applications awaiting a decision, guarantors to verify | Added | The officer's starting point is the work waiting for them, not the full list. |
| Applications and Members screens; an application screen with its timeline and per-guarantor Verify / Reject | Added | The loan workflow from part B needed screens. Rejecting asks for an optional reason, which goes to the audit log. |
| Admin overview: live KPIs, risk bands, decision outcomes, officer–model and rule–model agreement, recent activity, and the speech engine and device in use | Added | Practice interviews and applications are left out of every figure, as on Model & Evaluation. The engine and device come from `/api/health`, so a fallback to the CPU is visible. |
| Users and Audit log screens | Added | Account administration and the audit trail without the shell. The audit log filters by person, action, record type and date. |
| Member portal (`#/my`), phone first: applications with a six-stage timeline (Applied → Interview → Assessment → Decision → Guarantors → Approved), the officer's message, three plain reasons, what happens next, and the guarantor form | Added | Members need to see where they stand and add guarantors themselves. It shows no probability, risk class, SHAP number or officer note. The guarantor form asks for exactly the number still needed and checks each entry before sending. |
| Profile page for every role: name, role, email, linked Google account, change password, sign out of all sessions | Added | People can manage their own account. Changing the password ends every other session. |
| Practice badge on every practice interview, application, decision and comparator, including the member portal | Added | A practice record must never be mistaken for a real loan anywhere it appears. |
| Motion (the `motion` library) for entrances and state changes only; removed entirely under `prefers-reduced-motion` | Added | Motion helps people see what changed; for those who asked for less, content appears at once and nothing moves. |
| Skeleton loaders, toasts, modals, empty states | Added | Loading, confirmation and empty states look the same on every screen. |
| Every route is its own code-split chunk; no images beyond inline SVG | Changed | Branch connections may be slow. The landing page and member portal never download the staff screens. |
| All interface text in `frontend/src/strings.ts` | Changed | Ready for a Kikuyu translation: a second object of the same type can be swapped in. |

## Backend additions made for the dashboard

| Change | Reason |
|---|---|
| `GET /api/questions` from `src/chamapro/questions.json` | Specified; single source for the question script. |
| `GET /api/interviews` | Specified; the list screen. |
| Reads report the clip in progress as "transcribing" | Specified; the database still stores "queued". |
| `POST /api/interviews/{id}/decision` | Specified; immutable once made, enforced by database triggers. |
| `GET /api/responses/{id}/audio` | Not in the original list; Replay needs the stored clip after a page reload. |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | Authentication; every other endpoint except `/api/health` now requires a signed-in user. |
| `POST /api/auth/google`, `GET /api/auth/config`; `users.email` (unique, lower-case) and `sessions.auth_method` | Google sign-in for linked users; the session records which method was used. |
| `assessed_by` and `decided_by` on assessments and decisions | Records who made each one; nullable, so rows from before sign-in are left as they were. |
| `GET /api/questions?version=`, question sets v1 and v2 in one `questions.json` (`id, version, topic, order, text_en, text_kik, features`) | The dashboard loads the set an interview was created with. |
| `GET /api/applicant-form`; applicant `age, sex, education, marital_status`; `assessments.applicant_form` | The form's choices come from the classifier's encoding; the form values merged into the vector are stored with the assessment. |
| `interviews.question_set, language, mode`; `responses.source` | Migrated in place with ADD COLUMN: existing rows become v1 / kik / live / audio. |
| `POST /api/interviews/{id}/responses/typed` | Typed answers: no audio, no ASR. |
| `/api/health` reports the ASR engine and device actually loaded, per language | OpenVINO on the GPU falls back to the CPU, and a missing export to torch; the health check shows which happened. |
| Live statistics on `/api/results` exclude practice interviews | Practice runs are not operational data. |
| Alembic migrations (`src/chamapro/migrations`) replace `create_all` plus ADD COLUMN; `DATABASE_URL` selects SQLite or PostgreSQL (Supabase session pooler) | One schema history for both databases. The baseline adopts a pre-Alembic database without touching its rows; SQLite is backed up and upgraded in one transaction at startup; PostgreSQL is only ever upgraded by `alembic upgrade head`. |
| Immutability triggers on both dialects; PostgreSQL also blocks TRUNCATE and raises SQLSTATE 23000 | The audit-record guarantee must not depend on which database is used; 23000 makes both surface as an IntegrityError with the same message. |
| Row-level security, with no policies, on every PostgreSQL table | Supabase publishes the public schema through its Data API to anyone with the anon key; with RLS on and no policy those roles read nothing, while the backend (the table owner) is unaffected. |
| Roles admin, officer, member | Members get their own login and see only their own applications; every staff endpoint refuses them (403), and another member's application is a 404 so ids cannot be probed. |
| `members`, `loan_applications`, `guarantors`; `POST/GET /api/members…`, `/api/applications…`, `/api/guarantors/{id}/verify\|reject` | The SACCO workflow around an interview: who applied, for what, against which savings, and who guarantees it. An application's status follows its interview and then the decision. |
| Decision outcomes, `approved_amount_kes`, `guarantors_required`, `officer_notes`, `member_message` on `decisions` | Added by ADD COLUMN, so existing decisions are unchanged and immutable; they read with `outcome` equal to their old `decision`, and `decision` stays the coarse approve/decline/refer that the agreement statistics use. |
| `GET /api/me/applications`, `GET /api/me/applications/{id}`, `POST /api/me/applications/{id}/guarantors` | Member self-service: timeline, outcome, the officer's plain-language message and three reasons worded from the top SHAP factors. No probabilities, risk class, feature names or officer notes. Age, sex and marital status are never given as reasons: the member cannot act on them and naming one reads as discrimination. |
| `audit_log`, append-only by trigger, written in the same transaction as each create, status change, decision, guarantor action and user change; `GET /api/admin/audit` | Accountability for every step. Details hold ids, statuses, amounts and field names only: the log cannot be erased, so it holds no personal data that may later have to be. |
| `/api/admin/users…`: list, create, deactivate, reset password, change role, link a Google email or a member | Account administration without the shell. An admin cannot deactivate or demote themselves, so one active admin always remains; account changes end that user's sessions. |
| Audio storage interface: local files or a private Supabase bucket (`STORAGE_BACKEND`), replay by short-lived signed URL | Moving to Supabase must not make recordings public. The service-role key stays on the server; each stored clip remembers which backend holds it, so switching strands nothing. |
| Rule agreement in the live statistics (`rule_agreement`) | The SACCO rule against the model on live applications, next to the officer-agreement figure; practice applications are left out. |
| `GET /api/auth/profile`, `POST /api/auth/password`, `POST /api/auth/logout-all` | The profile page. Changing your password needs the current one, is rate-limited like sign-in, and ends your other sessions; signing out everywhere ends all of them. Both are written to the audit log. |
| `mode` on application lists, the application detail and a member's own applications | Practice applications carry a badge in every list, including the member portal. |
