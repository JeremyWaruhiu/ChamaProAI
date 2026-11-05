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
| A request that gets no answer within 15 seconds (30 s for the live statistics on Model & Evaluation and the admin overview, 90 s for the assessment) shows an error with a Retry button | Added | The wireframes show no failure states; a stalled server must never leave a screen spinning forever. |

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

## Member loan workflow, SACCO activities and the volunteer pilot

Migration `0004`. None of this has a wireframe; every row is an addition unless
it says otherwise. The trained model, the evaluation results and the assessment
pipeline are unchanged: `assess` runs as before, called with the member as the actor.

| Change | Status | Reason |
|---|---|---|
| Public sign-up at `/signup` (`#/signup`), only while `PILOT_INVITE_CODE` is set; invite code, phone, password and a consent box; consent version and time stored | Added | Volunteers need to join without an administrator. The consent text says what happens to their answers, and asks for a fictional applicant. |
| Volunteers sign in with their phone number or generated member number (`V-00042`) | Added | A username would be one more thing to remember on a phone. The number in any form counts as one key for the sign-in limit, so retyping it earns no extra attempts. |
| `members.phone` stored as `+254XXXXXXXXX`, unique when present; `POST /api/members` now returns that form | Changed | A duplicate must be a duplicate however it was typed. Staff-created members may still have none. Guarantor numbers are not members' and stay as typed. |
| A member's email is on `members.email`, not `users.email` | Added | `users.email` signs in with Google. If a sign-up form could set it, anyone could tie someone else's address to an account whose password they know. |
| Savings on the member record, "Self-declared, pending verification" until staff verify or edit them; age kept as a birth year | Added | The SACCO rule needs a figure before anyone has checked it, and must say so. A birth year does not go stale, and a birth date is not needed. |
| `joined_on` of a volunteer is the sign-up date until staff edit it | Added | Members cannot edit the verified fields, so a new volunteer sees the under-6-months warning until an officer corrects it. |
| "Apply for a loan": known fields read-only, live limit hint, warnings that never block | Added | The officer decides; the form's job is to set expectations. The API refuses read-only fields rather than ignoring them, so a client bug shows up. |
| A month calendar, not a native date input | Added | A native input cannot grey out weekends or holidays or say why. Closed days stay pressable, because a tooltip never shows on a phone: tapping one says "Jamhuri Day: public holiday". |
| Half-hour slots 08:30 to 16:00 (the last ends at 16:30); one upcoming interview per member; booking up to 90 days ahead | Added | One branch, one interview per slot. The limit per member stops one person holding every slot; the window keeps bookings inside the configured holiday list. |
| Bookings page (upcoming list and week calendar), confirm / reschedule / cancel / open interview; a rescheduled booking counts as confirmed | Added | The officer chose the new time. Opening a confirmed booking creates the live interview with the application and applicant form attached, and goes straight to the existing runner. |
| Member's application page: booking card, booking again after a cancellation, "What has happened" history | Added | Status changes and every time change, in words, in Nairobi time. |
| Practice interviews linked through `practice_interviews`, never `loan_applications.interview_id` | Added | That column is one interview per application and drives its status. Using it would have moved a real application to "assessed" and blocked the officer's own interview. |
| One question per screen, record / upload / type; review, then submit | Added | The same flow as staff, on the member's own endpoints, which return only what a member may see: no translation, extraction signals, engine errors, feature names. |
| The practice result is a sentence for each risk class, plus the existing reasons | Added | It tracks the class, as a result must, but never names it, and says it is not a loan decision. |
| Every answer must be ready before a member can submit | Changed | Staff may assess a partial interview; a volunteer's partial run would only produce a poor evaluation record. |
| Daily caps in `pilot_daily_usage`, raised by a conditional UPDATE, per Nairobi day; released if the assessment fails | Added | Counting assessments would let two requests at once pass the cap, and a Gemini outage would use up a member's day. Staff interviews do not count: the caps protect the pilot's budget, not the branch's work. |
| SUS questionnaire after submitting, once per interview; the server scores it; the member sees their own score only as computed by their browser | Added | Standard wording, optional. The pilot page gives the number of responses and of members, since one person may answer more than once. |
| SACCO events: staff create, change and delete; members and officers see upcoming ones | Added | Past events are filtered out when read, so nothing has to clean them up. Online links must be http(s), since they become links on members' phones. |
| Pilot page and CSV exports (`#/admin/pilot`), self-service interviews only | Added | Staff practice runs and demo rows are not evaluation data. Exports use member numbers, no audio, and escape cells a spreadsheet would run as a formula. |
| Member tabs drop their icons below 480 px; the sidebar says "Bookings" and "Events" | Changed | Three tabs must fit at 360 px. |
| No SMS or email when a booking changes | Deferred | The member sees the change on their next visit; sending messages needs a provider and a budget. |
| Kikuyu wording for question set v2 | Deferred | Needs a native speaker. A Kikuyu practice interview shows the English with a note that answers may be in Kikuyu. |

New screens are in `docs/screenshots/pilot-*.png` (desktop) and `pilot-*-390.png`
(390 px wide). Each was also measured at 360 and 430 px: nothing scrolls sideways.

### API changes for this work

| Change | Reason |
|---|---|
| `POST /api/auth/signup`, `GET /api/auth/signup` | Self sign-up. Separate from `/api/auth/config`, whose reply is fixed by its tests. |
| `/api/me/member`, `/me/home`, `/me/consent`, `/me/apply-options`, `POST /me/applications`, `POST /me/applications/{id}/booking` | A member's own record and application. |
| `/api/me/practice/...`, `POST /me/applications/{id}/practice` | Thin wrappers over the staff endpoints, each checking ownership first. Another member's interview, or a live one, is a 404. |
| `/api/booking/calendar`, `/booking/slots`, `/api/bookings...` | Booking; the calendar is for every role, the list and its actions for staff. |
| `POST /api/members/{id}/verify`; `email`, `savings_*` and `self_signed_up` on `MemberOut` | Verification, audit-logged by field name. |
| `savings_self_declared` on `loan_applications`, `booking` and `practice_interviews` on the application detail | Officers can see what they are relying on. |
| `/api/events`; `/api/admin/pilot`, `/admin/pilot/export/*.csv` | Activities and evaluation. |
| Row-level security, with no policies, on the five new tables | As on every other table: Supabase's Data API must read nothing. |

## The member database (phase 1 of 5)

Migration `0005`. The interview is to become a short self-service conversation, so
everything the eight v2 questions collected must already be held in the database.
This phase is that database only: no chat, no speech output, no change to the
classifier, the assessment pipeline or how a decision is made.

| Change | Status | Reason |
|---|---|---|
| `member_profiles`, one current row per member, keyed by the classifier's inputs | Added | What the interview would ask. Sex and education are stored as the applicant form has them; `profile_features` gives them to the classifier as `is_female` and `education_level`, the keys `score()` takes. |
| Source, updated-at, verified-by and verified-at per field group (personal, household, income, assets, credit), as columns | Added | Queryable ("whose income is unverified?"), and a member's edit to one group does not undo an officer's check of another. |
| `member_profile_history`, a whole-row snapshot per change, immutable by trigger on both databases | Added | What was believed on any date can be recovered. It holds personal data and cannot be erased through the application: see the open questions below. |
| Date of birth replaces birth year where the profile has it | Changed | 0004 chose a birth year because a date was not needed; the supervisor's specification now asks for one. A profile without one falls back to the birth year. |
| `sacco_loan_use` and `lost_as_guarantor.sacco` derived, never stored or accepted | Added | The SACCO already knows them. The API refuses them as unknown fields. |
| A defaulted loan counts as `sacco_loan_use` 2 | Added | The specification gives 0 never, 1 repaid, 2 active. A defaulted loan is still owed; calling it 1 would record it as repaid and flatter the member. |
| No loan and no ledger entry at all: those two features are missing, not 0 | Added | A member not yet on the ledger has no records to read. Sending "never borrowed" would state something nobody knows. |
| `member_accounts` and `account_entries`, append-only by trigger, balances always computed | Added | A stored balance can disagree with its history; a sum cannot. |
| Entry rules as CHECK constraints, with `account_kind` on each entry held true by a composite foreign key | Added | The database itself refuses a withdrawal from deposits, whichever code tries it. |
| `loan_accounts`, repayments as ledger entries, `days_in_arrears` computed; money pays the oldest instalment first | Added | As specified. Recoveries from guarantors count towards the loan. |
| `guarantor_pledges` holds no amount; capacity is worked out when it is needed | Added | Deposits move; a figure pledged last year would be stale. |
| `guarantors` gains `member_id`, `pledge_id` and `loan_account_id`; `application_id` nullable | Changed | Reuses the one table and review flow. A loan from before the system has no application, but its guarantors still hold capacity; a second table for them would have been the second flow the specification rules out. |
| Available capacity also subtracts guarantees on applications not yet paid out | Added | Beyond the specified formula. Without it the same balance could be pledged to two applications at once. Capacity itself is as specified. |
| A typed guarantor number that is a member's links to them, but a pending typed row holds no capacity | Added | Anyone can type a number; that must not use up someone's capacity. It counts once an officer verifies it. |
| A member sees whether their guarantor can guarantee, not how much; officers see the figure | Added | Capacity is close to a deposit balance: another member's confidential savings. |
| `POST /me/profile`, `PATCH /me/profile`, `POST /me/profile/confirm`, `POST /members/{id}/profile/verify` | Added | An edit is saved at once as `member_update`, unverified, as specified. "Still correct" is an extra: without it the date only moves when something changes. |
| The registration form appears because the sign-up reply says so, and nothing brings it back | Added | "Once" needs no stored state. Skipped, it is reached through "Change my details". |
| A failed claim says the same thing whatever was wrong | Added | Otherwise sign-up tells anyone who is a member. |
| A member number that does not match refuses instead of creating a new member | Changed | The specification says otherwise create. Someone who typed a number thinks they are claiming a record; silently making a second one would hide their savings from them. |
| A claim keeps the SACCO's name for the member, and does not count them as a pilot volunteer | Added | The name typed at sign-up is unverified. They did not join through the pilot. |
| The last ten entries are per account, under a disclosure | Added | Ten overall could hide an account entirely; thirty open rows are too long for a phone. |

### Changes to what 0004 did

| 0004 | Now | Applies to |
|---|---|---|
| The SACCO rule read `loan_applications.sacco_savings_kes` | Reads the deposits balance: live until the application is decided, then as it stood at the decision | Members with deposits entries by then. Others keep the column, so every row that exists today reads as before. |
| A typed savings figure was stored | The balance is stored; `POST /applications` ignores what is typed, and the wizard shows the balance read-only | Members on the ledger |
| A member could declare savings, an officer could verify a figure | Both refused with 409; `POST /members/{id}/verify` still corrects `joined_on` | Members on the ledger. Without a ledger, declaring and verifying work as before. |
| `savings_status` was none, self_declared or verified | Also `ledger` | |
| `DELETE /members/{id}` refused only with applications | Also refuses with a profile, ledger, loan or pledge | |
| Live statistics took four queries | Five: one more for the savings, however many applications | |
| The member's age was this year minus the birth year | Exact, from the date of birth, where the profile has one | |
| Member tabs: three, scrolling if needed | Four, wrapping to two rows below 480 px | |

### Not built in this phase

No endpoint posts a ledger entry, pays out a loan, or adds or withdraws a pledge: the
functions exist in `ledger.py` and are used by the seed and the tests. So on a live
database nobody reaches the ledger yet, and an approved application's guarantors go
on holding capacity until a payout exists to release them. A member's exit, where
deposits are refunded, has no entry type: `withdrawal` from deposits is refused.

### Open questions

- **Erasure.** `member_profile_history` keeps date of birth and income in a table the
  application cannot delete from, and a member with a profile can no longer be deleted.
  The audit log was kept free of personal data for exactly this reason. Under the Kenya
  Data Protection Act 2019 the project needs a decided answer to an erasure request.
- **Claiming is not proof of identity.** Member number and phone number are not secrets,
  and a claim now opens someone's balances, date of birth and income. It is behind the
  invite code and the sign-up rate limit, and audit-logged. A one-time code sent to the
  phone is needed before real members use it.
- **FinAccess in the demo database.** The generated profiles are row-level values from
  licensed microdata under invented names, with no county or respondent number. The
  file stays under `data/` and out of git and the image, but `docker-compose.yml`
  serves it. Check the licence before a public demo.

### API changes for this work

| Change | Reason |
|---|---|
| `GET /api/me/sacco`, `GET /api/members/{id}/sacco` | My SACCO and the officer's member page; the same builder, with figures only for staff. A fixed number of queries however many rows. |
| `GET /api/me/applications/{id}/guarantor-offers`, `POST /api/me/applications/{id}/guarantors/pledged` | Standing guarantors with enough capacity, becoming ordinary `guarantors` rows. Fewer than needed is allowed; the rest can be typed. |
| `member_no` on `POST /api/auth/signup`; `claimed` and `profile_due` in its reply | Claiming a member; whether to show the registration form. |
| `from_ledger` on `MyMember`; `savings_from_ledger` on the application detail | Screens can say where the figure came from. |
| Row-level security, with no policies, on the six new tables | As on every other table. |

## The decision engine and ledger operations (phase 2 of 5)

Migration `0006`. There is no chat or speech yet: the next phase calls what is here.
The trained model is unchanged and is not retrained. The language model decides
nothing: the classifier scores the person, the SACCO rule and an affordability check
score the request, and a fixed, versioned policy picks the outcome. Policy version
`2026.11.1`.

### The policy

`decisions.settle` is a pure function of the facts: the first row that applies decides.
A row can only send someone towards a person, never away from one.

| # | When | Outcome | Reason |
|---|---|---|---|
| 1 | No deposits entries on the ledger | Refer | The figure is what the member said, or at most what an officer typed. Comes first, so self-declared savings always refer, even for someone who would otherwise hear "not now". A rule refusal built on an unchecked record should come from a person. |
| 2 | Membership under 6 months | Not now, with the months left | A hard rule that time will satisfy. The SACCO's rule, not the model's view. |
| 3 | No guarantors at all: no pledge and nobody named | Not now | A hard rule, and the reason says what to do: ask two members to pledge. |
| 4 | A clarification is still to be answered | Clarify | Nothing is settled while a question could change the answer. Cannot be committed. |
| 5 | High risk | Refer | The model alone never declines anyone. |
| 6 | A defaulted loan, or an active one behind | Refer | **Added.** The specification's conditions are necessary, not sufficient. The model only sees "currently borrowing", and a payout with no human eye to someone already behind would be hard to defend. |
| 7 | No term, or no income, or the member would not confirm income or chama details | Refer | The policy cannot settle what it cannot compute. |
| 8 | Medium, with no clarification answered | Refer | As specified: Medium needs an answered question to go on. The wording is the same as for row 5, so a member cannot tell the class from it. |
| 9 | Above either maximum, and the lower is under half the original request | Refer | As specified: an offer must be at least half. |
| 10 | Above either maximum, and the offer is above the automatic limit | Refer | The limit applies to what would be paid. |
| 11 | Above either maximum, and the guarantors do not cover the offer, or need someone only named | Refer | As row 12, at the offered amount. |
| 12 | Otherwise, above either maximum | Reduced offer: the lower maximum | The member must accept. Holds no capacity until then. |
| 13 | Within both maximums, above the automatic limit (KSh 50,000) | Refer | As specified. |
| 14 | Guarantors do not cover it | Refer | After C5 has been asked: nothing automatic is left to try. |
| 15 | It needs a guarantor who was named and has not pledged | Refer | **Added.** C5 can name anyone, and they have agreed to nothing. Phase 1 already held that typing a member's number must not use up their capacity; an automatic payout on one would do worse. |
| 16 | Otherwise | Approve and pay out | All checks pass, deposits on record, within the limit, Low (or Medium after an answer), guarantors pledged. |

The checks, each kept in the trace with its values: deposits on record, membership,
amount within 3 x deposits, at least two guarantors, guarantor capacity, affordability,
automatic limit, risk, no arrears.

### The arithmetic

    instalment   = P x r / (1 - (1 + r)^-n), rounded up to a shilling, r = LOAN_INTEREST_MONTHLY
    limit        = AFFORDABILITY_RATIO x (income + expected return - loan instalments - chama instalment)
    rule maximum = 3 x deposits balance
    capacity     = two or more guarantors whose free capacity covers (amount - own free deposits)

The largest affordable amount is the largest whole shilling whose rounded-up instalment
is within the limit. That is why 1/3 of KSh 20,000 over 6 months gives KSh 38,632, not
the KSh 38,636 the formula gives before rounding.

### Clarifications

At most two per evaluation, in priority order, each with its reason and what it sets. A
key present in the overrides means the question was asked, and null means no answer, so
no question can be asked twice whatever the caller does. Re-evaluated after each answer.

| Id | Condition | Sets | Reading of the specification |
|---|---|---|---|
| C1 | Term missing | `term_months` | |
| C2 | Income older than `PROFILE_STALE_DAYS`; or missing; or unverified and among the top three SHAP drivers | `monthly_income_kes` | "Older" fires alone, because a stale figure feeds affordability whatever the model makes of it. "While among the top three" qualifies "unverified" only. Missing counts as older than anything. |
| C3 | Instalment within 15% of the limit, either side, and an income-generating purpose | `expected_monthly_return_kes` | Added to income for affordability only. The purpose is matched against a fixed word list; it decides nothing but whether to ask. |
| C4 | `chama_loan_use` missing or stale | `chama_loan_use`, `chama_instalment_kes` | |
| C5 | Guarantor capacity short | `extra_guarantor` | Looked up by number and name; says only found or not found. |
| C6 | Above both maximums | `accepted_amount_kes` | |

A question whose answer cannot change the outcome is not asked: self-declared savings
ask only C1 (the record needs a term), a hard rule failure asks nothing, High asks only
what can move the score (C1, C2, C4), and an amount an officer must decide either way
asks only C1 and C6. C3 and C6 wait while C1, C2 or C4 are open, since those change the
figure they turn on. The cap is per evaluation, so a conversation has at most six.

"Stale" counts from the group's last change, last check, or the member's own "still
correct". Not `confirmed_at`, which moves when any group is edited or checked: an officer
checking someone's household says nothing about their income.

### Other decisions

| Change | Status | Reason |
|---|---|---|
| Affordability is a third of (income minus obligations) | Decided | The specification's wording. The stricter banking convention, a third of income minus obligations, gives KSh 7,000 instead of KSh 9,000 on KSh 30,000 with KSh 3,000 owed. A one-line change if the SACCO prefers it. |
| Own deposits in the capacity check are net of what the member guarantees for others | Decided | Beyond the specified "own deposits". One balance cannot back two loans. The same when they guarantee nothing. |
| A verified savings figure with no ledger also refers | Decided | "On record" means the ledger. A typed figure, even an officer's, has no history. |
| An interview row with `mode = self_service` holds each decision's assessment and decision | Added | Assessments and decisions belong to an interview, are immutable by trigger, and every screen reads them through it. Left out of the live statistics and the interviews list, as practice runs are. |
| `self_service_runs` links each decision to its application | Added | `loan_applications.interview_id` moves on: to a second run when an offer is accepted, to the live interview when a referral is booked. The record of what the system decided must not. |
| Accepting an offer re-runs the engine at that amount and records a second decision | Added | Capacity can have been spent since the offer. An approval pays out; anything else goes where it says. No question is asked at that point. |
| `commit` re-runs the engine under the locks and compares with what the member was told; a difference is a 409 with nothing written | Added | Nothing trusts an evaluation passed in. The API sends `expected_outcome` and `expected_amount_kes` for this. |
| One open self-service application per member | Added | A second, with a new key, would not see a loan not yet paid out. |
| A referral with no term records 12 months | Added | The column is required. The trace says no term was given. |
| Guarantor shares: the need split evenly, smallest capacity first, at least KSh 1 | Added | A `guarantors` row must hold something, even when the member's own deposits cover the loan. |
| `not_now` is a new outcome, never open to officers | Added | An officer has "decline". Its coarse decision is decline, for the statistics. |
| Automatic payouts reversible for `REVERSAL_HOURS`; an officer's payout has no window | As specified | The window is specified for automatic ones. The same rule applies to both: refused once the money has been drawn, or a guarantor has paid towards it. A reversal refunds repayments first, then takes the principal. |
| Paying out releases guarantors still pending | Fixed | Phase 1 left them holding capacity on an approved application forever. |
| Paying out checks every verified guarantor's capacity | Added | Verifying does not, so two applications can be verified against one balance. The payout is where it is stopped. |
| The refund also refuses a defaulted loan's guarantor, until recovered in full, and an open application; it ends pledges in both directions | Added | "Guarantee nothing" must include what they still answer for. A member who has left backs nobody. |
| `POST /api/self-service/.../accept` and `.../decline` | Added | Not in the specification's list, but reduced offers wait for the member's acceptance. |
| The policy version gets a hash of the thresholds if any differs from its default | Added | Thresholds are configuration, so a bare version could mean two policies. |
| A member sees no class, probability, SHAP value or guarantor's capacity | As before | Built field by field, like every member view. |
| The system user is inactive, has no usable password and a role no endpoint admits; the admin's list and actions do not see it | Added | A row every automatic decision points at must not be something anyone can sign in as or switch on. |
| `_migration_engine` runs with foreign keys off, and checks them before committing | Changed | SQLite cannot change a CHECK without rebuilding the table, and with foreign keys on it cannot drop a table others point at. This is SQLite's own documented procedure. |

### Locking

`ledger.lock_members` takes `SELECT ... ORDER BY id FOR UPDATE` on the members, then
their accounts, always lowest id first and all in one call. A balance is a sum of rows
that are only added, so the member row is what anyone spending it queues on. On SQLite
there are no row locks; inserting the idempotency key takes the single write lock first.
`sacco.use_pledges`, from phase 1, now locks too. Idempotency keys are per user, held in
`idempotency_keys`, and go in first in the request's own transaction: a second request
with the key waits on the unique index and gets the stored reply.

### Seed

No member copies a FinAccess respondent's row. Respondents are put in strata of income
band (under 5,000; 5,000-14,999; 15,000-29,999; 30,000 and over; unknown) x household-size
band (1-2; 3-4; 5-6; 7 and over; unknown). Each member takes personal, household, income,
assets, purchases and borrowing fields from six different respondents of one stratum,
drawn by the fixed seed in the survey's proportions of strata. A stratum of fewer than six
is not used, and a composite matching a real row is drawn again. `scripts/seed_members.py`
documents it. A profile's group timestamps now follow its last confirmation rather than
the build time, so generated members can be stale. The values are still derived from
licensed microdata: this reduces the licence question and does not remove it.

### Changes to what earlier phases did

| Before | Now | Applies to |
|---|---|---|
| A reversed loan did not exist | `sacco_loan_use` ignores it, arrears are 0, capacity is released | Reversed loans |
| `POST /me/applications/{id}/booking` refused an application with an interview | Allowed on a referral held by an automatic decision; cancelling returns it to the referral | Self-service referrals |
| `GET /api/interviews` listed every interview | Leaves out automatic decisions' records | `mode = self_service` |
| `channel` did not exist | `branch` on every existing application | All rows |

Screens are in `docs/screenshots/decisions-*.png`. Each was measured at 360, 390 and 430 px:
nothing scrolls sideways.

### Open questions

Settled in phase 3, which see: typed income, Medium after C1, existing loans and the 3 x rule,
notice to guarantors, and Data Protection Act s.35. The capacity oracle and erasure remain open.

- **A member can type their income.** A C2 answer replaces the profile for the score and
  for affordability, unchecked, and up to KSh 50,000 can then leave automatically. In the
  demo, KSh 10,000 becoming KSh 30,000 moves Njeri from Medium to Low. The specification
  asks for this behaviour; a real SACCO would want a limit, such as referring any answer
  far above the profile, or above what deposits suggest. The trace records
  that the figure came from the conversation; nothing stops it.
- **Medium after C1.** Giving a repayment term counts as "a clarification answered", which
  clears a Medium score, though a term says nothing about the person. Only C2 and C4 can
  move the score.
- **Existing loans and the 3 x rule.** The rule compares the request with deposits, as
  specified, not outstanding loans plus the request. Only affordability sees a second loan.
- **Guarantors are not told.** A standing pledge becomes a live guarantee with no message
  to the guarantor and no ceiling beyond their capacity. A real guarantor would need notice.
- **Automated decisions and the Kenya Data Protection Act 2019.** Section 35 concerns
  decisions based solely on automated processing. Approvals and "not now" here have no
  human in them; the consent text does not mention them. "Not now" tells the member what
  to do, but does not offer a person. To be settled before real members use it.
- **A capacity oracle.** Whether a loan clears can tell a member something about a
  guarantor's capacity by trying different amounts. No figure is returned, and evaluations
  are limited per hour, per member, per process.
- **Erasure.** Each trace records guarantors' member numbers and free capacity in an
  immutable row, which adds to the phase 1 question.

### API changes for this work

| Change | Reason |
|---|---|
| `POST /api/self-service/evaluate`, `/commit`, `/applications/{id}/accept`, `/decline` | For the next phase. Member role, own record, rate limited. The body has no member id. |
| `POST /api/members/{id}/deposits`, `/withdrawals`, `/refund-deposits`, `/pledges`; `POST /api/pledges/{id}/withdraw`; `POST /api/applications/{id}/payout`; `POST /api/loans/{id}/repayments`, `/reverse` | The ledger operations. Officers and admins, audited, `Idempotency-Key` required. |
| `GET /api/automatic-decisions`, `/{id}` | The officers' page. Two queries for the list, however many rows. |
| `policy_version` on `DecisionOut`; `self_service` in `mode`; `offered` and `reversed` in application status; `reversed` in loan status; `not_now` in outcome | What the screens must now show. Officers cannot choose `not_now` or start a `self_service` interview. |
| Row-level security, with no policies, on the two new tables | As on every other table. |

## The conversation backend and speech output (phase 3 of 5)

Migration `0007`. Policy version `2026.11.2`. A member applies by conversation, by text or
voice, in English or Kikuyu. There is no chat screen yet: phase 4 builds it on the API here.
The classifier is unchanged and is not retrained. Gemini writes nothing the bot says and
decides nothing.

### Rulings on the phase 2 questions

| Ruling | How it is built |
|---|---|
| Income: increases to `UNVERIFIED_INCREASE_TOLERANCE` (0.30) over the profile accepted; more is rescored, shown, and referred | `decisions.income_needs_officer`. Reason code `income_unconfirmed`, whose message says "income needs officer confirmation". A check row in the trace gives the figures. A decrease is always accepted. |
| Only C2, C3, C4 clear Medium | `decisions.CLEARS_MEDIUM`. |
| 3 x rule: 3 x deposits minus outstanding principal on active SACCO loans | `ledger.outstanding_principal`, on the reducing balance at the configured rate. Used by the engine only; see below. |
| Pledges have a ceiling, and a pledge used on an automatic approval posts a notice | `guarantor_pledges.max_amount_kes`, `member_notices`, shown on My SACCO. The ceiling covers everything the pledge holds for that borrower, on loans still owed and on applications not yet issued. |
| s.35 | Consent is the second thing the bot says, and is stored with a version that is a hash of its wording. `POST .../review` makes a referral on any automatic outcome. "Not now" can be booked directly. |
| At most 3 clarification questions, then refer | `CONVERSATION_MAX_QUESTIONS`. Reason code `question_cap`. If the third answer settles it, there is no referral. |
| `seed_demo.py` prints the database written | `database_written()`, from the engine, password hidden. |

Njeri's profile income is now KSh 18,000 (Medium, income in the top three drivers). KSh 22,000
is 22% up, inside the band (the ceiling is KSh 23,400), and the real classifier calls it Low, so
it gets the reduced offer of KSh 45,000. KSh 30,000 refers.

### Conversation

`conversation/machine.py`. Each state is the question last asked:

    G1 -> CONSENT -> G2 -> R1 -> [CHECK_AMOUNT] -> evaluate -> C1..C6 -> CONFIRM -> commit -> O1..O4 -> END

`conversations` holds where it has got to; `conversation_turns` is append-only by database
triggers on both databases. A reply does its slow work with no transaction open. `busy_until`,
taken in its own commit, stops a second reply being worked on at once, and lapses if a process
dies. Speech comes next, and then a single commit writes the member's turn, the bot's turns and
the new state. The turn is never filled in later. A decision commits on its own under a key made
from the conversation's id, so a failure before the last commit changes nothing about the
conversation, and answering again finds the decision instead of paying twice.

A reduced offer on CONFIRM goes through the phase 2 path as it stands: commit (offered), then
accept. A referral or "not now" commits at once, with no CONFIRM.

### Decisions the brief left open

| Decision | Why |
|---|---|
| Phase 1 has no "profile update request", though the brief says "as phase 1 does". Added as a `member_profile_history` row, `change = update_request`, holding the unchanged snapshot and what was asked for | The nearest thing phase 1 has, and already append-only. The audit log gets group names only. Staff read them in `update_requests` on the member's SACCO page; no screen shows them yet. |
| A yes at G2 is not a confirmation of the profile and does not answer C2 (phase 4: it refreshes what was read out, and a stale income is not read out) | A confirmation would reset the income's age, and Njeri would never reach C2. An income corrected at G2 does count as C2 and is held to the tolerance. |
| A stated income with no profile figure refers (`income_unconfirmed`) | There is nothing to compare it with, and it is the same hole the ruling closes. |
| CHECK_AMOUNT guards every money figure (R1, C2, C3, C4), not only the loan amount | A wrong income moves the score as a wrong amount does. It does not count towards the 3 questions. |
| Consent unclear twice is treated as not given | It must never be inferred. |
| A yes to CONSENT or CONFIRM from the model alone needs confidence of at least 0.8; a model and lexicon that disagree mean REASK | Those two answers give consent and move money. Other model readings need 0.5. |
| "Then refer" before there is an amount says OFFICER_HELP, with no O3 | O3 says an officer will look at "your application", and there is no application to look at. |
| C6 "no" refers (`offer_declined`) rather than offering the same figure | They have just turned it down. |
| A chama "yes" with no instalment is REASK | Treating it as KSh 0 would overstate what they can afford. |
| A referral's actions offer booking only; review of one is a 409 | It is already with an officer. Every other automatic outcome offers review. |
| Review of a paid-out loan is recorded as a referral and the loan stands; the application keeps pointing at the decision that paid it | An officer can reverse it within the window. Moving the application would disturb that. |
| A pledge from before `0007` has no ceiling and backs no automatic decision. An officer's branch review can still use it | Nobody can say what the guarantor would have agreed to. The officer's API now requires a ceiling for new pledges, and the guarantor can set their own. |
| A reversal posts a second notice to the guarantors | Otherwise "You are now guaranteeing" stays on their page and is false. |
| Five extra template ids: `C2_NEW`, `O4_GUARANTORS`, `OFFICER_HELP`, `ACTION_REVIEW`, `ACTION_BOOK` | C2 and O4 as written have nothing true to say with no income on record, or no months to wait; the rest have no text in the brief. All need Kikuyu too. |
| `POST /api/self-service/commit` needs `consent_version` | Otherwise the HTTP route is a way round the consent. An evaluation returns the wording and the version. |
| Gemini on a server: `CONVERSATION_GEMINI_LIVE=1` | uvicorn has no `--live`. Off by default, so nothing is sent by accident. |
| `transcribe_now` shares a lock with the worker | The ASR pipeline is not thread-safe. A reply waits for the clip in progress and not for the queue. |
| Age, sex and marital status have no plain label in `explain`; the count left out is given | `member_text`'s rule: naming one as counting against someone reads as discrimination. Staff still see them. |
| Reply is a multipart form, not JSON | One route takes text or a file. |

### Kikuyu

`kikuyu_numbers.py` round-trips every number from 0 to 999,999. The brief's vocabulary is in one
place at the top. Its docstring separates what the brief gave from what was added to complete the
range: zero, the agreement of `magana`, the use of `na`, the comma, and the spelling variants. None
of it has been checked by a speaker. Nor has `lexicon.py` beyond the brief's four forms. An amount
above 999,999 is left as a figure in Kikuyu text.

### Open questions

- Settled in phase 4, which see: what a member sees in `explain`, C5's figure, a member hearing a
  stale income twice, and the 3 x rule in the branch flow.
- **Latency on Supabase.** On SQLite a reply is 9 to 21 queries, and the reply that pays out is
  about 53. At ~200 ms a round trip, that is 2 to 4 s and about 10 s respectively, before speech.
  Not measured there; the figures are queries x the round trip in `test_query_counts.py`.
- **Speech with slots is slow on a CPU.** See below. Sentences with amounts cannot be pre-warmed.
- **Licence.** Both voices are CC-BY-NC 4.0. A real SACCO deployment would need other voices.
- **"Good morning"** is fixed text, at any hour.
- Still open from earlier phases: the capacity oracle, one-time codes for claiming a member,
  erasure (conversation turns are now also immutable, and a recording is personal data).

### Timings on this machine (8 threads, no Gemini)

| What | Time |
|---|---|
| Paza, OpenVINO int8 on the GPU, one 5.4 s corpus clip | 13.8 s first, then 4.9 s and 3.2 s; 27 s to load |
| `mms-tts-kik` on the G2 sentence (English text, 8.8 s of audio) | 2.4 to 4.3 s; 7.3 s to load |
| `mms-tts-eng` on the G2 sentence (9.5 s of audio) | 3.4 to 5.7 s; 2.0 s to load |
| Rehearsal of Wanjiru, English, typed, cold speech cache | 17.4 s of server work across 5 replies; 33.9 s with start-up |
| The same, warm cache | 2.8 s of server work; 6.9 s with start-up |
| Its slowest step, cold: "Yes, go ahead" | 2.9 s evaluate and commit, 4.0 s speech |

The kik voice read English text because the Kikuyu templates are empty. The time is
indicative and says nothing of how it sounds. The first evaluation in a process adds about 2 s to
load the classifier. Over real HTTP, one voice reply through Whisper took 14.2 s on its first use.
Of that, 9.2 s was ASR, including loading the model, and 3.3 s was speech.

### API changes for this work

| Change | Reason |
|---|---|
| `POST /api/conversations`, `POST .../{id}/reply`, `GET .../{id}`, `GET .../{id}/turns/{seq}/audio` | The conversation. |
| `POST /api/self-service/applications/{id}/review` | s.35. |
| `PATCH /api/me/pledges/{id}`; `max_amount_kes` on `PledgeOut`, for the guarantor and staff only; required on `POST /api/members/{id}/pledges` | The guarantor's ceiling. |
| `notices` on `SaccoView`; `update_requests`, staff only | Shown on My SACCO, at 360, 390 and 430 px: nothing scrolls sideways. |
| `consent_version` required on commit; `consent_version`, `consent_text` on an evaluation | s.35 on the HTTP route. |
| `review` in `AutomaticDecision.trigger` | The officers' page lists them. |
| `not_now` applications can be booked directly; a cancelled booking returns them to `declined` | "Not now" offers the booking flow. |
| Row-level security, with no policies, on the three new tables | As on every other table. |

## The phone chat and the presenter view (phase 4 of 5)

No migration. Policy version `2026.11.3`, because a yes at G2 now changes when C2 fires. A member
applies by talking on a phone (`#/my/chat`), and a laptop follows on `/present`.

### Rulings on the phase 3 questions

| Ruling | How it is built |
|---|---|
| Members never see the class or probabilities | The turn's record keeps everything (`machine.explain`). A member gets `member_text.plain_explain` of it, built field by field: the reason, each check as a sentence in their own figures, the top three drivers as sentences. `reason_code` and the check ids stay out as well. Officers and admins read the record through `/api/present/...`. |
| C5: "You need one more guarantor for this loan. Who else could guarantee it?" | No slot any more. |
| `comparator.py` stays as it is | Unchanged. |
| G2 leaves out a stale income; a yes refreshes the groups it read out | New template `G2_NO_INCOME`. The groups read out are held in the context, and a yes writes a `confirm` row in `member_profile_history` naming them. `decisions.last_confirmed` now takes a group; a `confirm` with no groups is the whole profile, as before. A correction refreshes nothing. |

### Template ids that need a Kikuyu text

All 24 are empty: `G1`, `CONSENT`, `G2`, `G2_NO_INCOME`, `R1`, `C1`, `C2`, `C2_NEW`, `C3`, `C4`, `C5`, `C6`, `CHECK_AMOUNT`,
`REASK`, `CONFIRM`, `O1`, `O2`, `O3`, `O4`, `O4_GUARANTORS`, `OFFICER_HELP`, `END`, `ACTION_REVIEW`, `ACTION_BOOK`.
Filling `CONSENT` changes the consent version. Also English only, and not templates: the reasons and
check sentences in `member_text.py`, and the screen's own words in `strings.ts`. The quick replies
`Ĩĩ` and `Aca` come from the lexicon, which no speaker has reviewed.

### Decisions the brief left open

| Decision | Why |
|---|---|
| A yes at G2 refreshes an income's age but does not answer C2 | An unverified income among the top three drivers is still asked at C2, right after the member said yes to it. Counting that yes as C2 would clear a Medium score with no new information. A policy change, left for you. |
| Ten SHAP values kept on evaluations only: `score(top=)`, default 8 | The branch interview's stored assessments stay as they were. |
| The SHAP chart's axis is "in the member's favour", not raw SHAP | Values are for the class predicted at that evaluation, so a raw +0.3 for Medium and +0.3 for Low point opposite ways. Comparing across C2 needs one direction. Say so if asked: for Medium it is the same approximation as `member_text`. |
| The faint bars show the last evaluation that differs, not simply the one before | The yes at CONFIRM re-scores the same answers. The C2 movement would vanish at the end otherwise. A stepper shows any evaluation. |
| Stages are held in memory, by conversation, and polled | The reply is one request, and the record is written only at its end. With more than one worker a screen sees no stage, and nothing else changes. |
| The reply still waits for speech; audio is fetched after the text | Turns are append-only, so `audio_ref` cannot be filled in later. Warm, this costs nothing. An uncached sentence delays the text by about 3 s. |
| One audio element plays everything, unlocked by playing silence inside the tap | iOS allows later play only on the element it saw tapped. If the browser refuses anyway, *Tap to start* comes back. Pressing the microphone stops the bot. |
| Yes and No appear on exactly the three states asked for | C6 and G2 are also yes/no questions, but a bare "no" at G2 only gets REASK. |
| The newest member bubble opens its details; older ones close | A phone screen holds about two turns. |
| `#/my/chat/:id` keeps a finished conversation's outcome across a reload | "Current" finds only open ones. |
| `/present` redirects to `#/present` | As `/signup` does: the address is easy to say. |
| A referral can now be booked from the member's application page | The API allowed it since phase 2, but the screen offered it only on a draft. Found by following *Book a time* in the browser. |
| Reset acts only on `seed_tag` `demo-db:wanjiru` and `demo-db:njeri` | Only a `--demo-db` build has them, so elsewhere it is a 404 and the button does not show. |
| Reset ignores the reversal window and reports money already drawn instead of forcing it | A rehearsal may be days old. It uses the ordinary reversal: compensating entries, notices, audit. Their other applications go to `declined`, with bookings cancelled. It also clears those two members' conversation rate limits. |
| Warm-up does more than Paza: the audio libraries (about 8 s on the first upload), the classifier and SHAP (about 7 s on the first evaluation), the English voice | Each was measured in front of a member in the browser run. `ASR_WARM=0` turns off the ASR and classifier warm-up; `ASR_WARM_ENGLISH=1` also warms Whisper. |
| Njeri's script has "12 months" between the request and the income | R1 extracts no term, so she hears C1. The brief's list leaves it out. |

### Things to know

- **C5 needs a name and a member number.** The new wording asks only who. A name alone gets REASK,
  then a referral, because `named_member` looks up both. Wanjiru and Njeri never reach C5.
- **`data/demo.db` is at revision 0006, from before phase 3.** Its pledges have no ceilings and
  Njeri's income is 10,000. The demonstration does not run on it until it is rebuilt, which
  issues new passwords. `warm_demo.py` says so and stops.
- **Reversed rehearsals stay in the ledger**, as they should. My SACCO shows them.

### Timings on this machine (8 threads, Paza on the GPU, warm cache)

`scripts/warm_demo.py`, typed answers through `service.reply`, no Gemini, English voice in both
languages because the Kikuyu templates are empty. Milliseconds of server work:

| Turn | Wanjiru en | Wanjiru kik | | Turn | Njeri en | Njeri kik |
|---|---:|---:|---|---|---:|---:|
| start | 5 | 9 | | start | 5 | 5 |
| consent | 9 | 12 | | consent | 11 | 9 |
| G2 | 10 | 9 | | G2_NO_INCOME | 10 | 8 |
| request | 65 | 67 | | request | 70 | 77 |
| term | 81 | 62 | | term | 516 | 360 |
| yes, paid out | 123 | 159 | | income | 162 | 668 |
| | | | | yes, paid out | 741 | 821 |
| **Total** | **0.29 s** | **0.32 s** | | **Total** | **1.51 s** | **1.95 s** |

| Voice, over HTTP | Time |
|---|---|
| Paza alone, standalone | 18 s to load, 7.4 s first clip, 2.9 s second |
| A 2.6 s webm reply, straight after warm-up, nothing else running | 2.1 to 3.1 s per turn, five turns |
| Through a real quick tunnel | 2.4 s, release to reply on screen |
| The final browser run: two Chromium pages and a fake microphone on the same machine | 1.6 to 2.2 s, release to reply on screen, five turns |
| One earlier browser run, same code path | 10, 10, 5, 3 and 4 s of ASR |

The slow run was not explained: it did not come back in the runs after it, and nothing else in the
run marked it out. So allow for a first voice turn of about 10 s on the day, and rehearse. Gemini
would add to every line: it was not measured, since no test may call it.

Screens are in `docs/screenshots/chat-*.png` and `present-*.png`. The voice turns come from
Chromium's fake microphone playing one corpus clip, with a stand-in for Gemini, so under them the
transcript is that clip and the English is scripted: they show the screen working, not what Paza
heard of those answers.

### API changes for this work

| Change | Reason |
|---|---|
| `explain` on a member's turn and reply is now `MemberExplain` | The ruling. |
| `outcome` on replies and details; `busy` on the brief; `GET .../current`; `GET .../stage` | The outcome card, carrying on after a reload, the stage indicator. |
| `GET /api/present/conversations`, `/{id}`, `/{id}/turns/{seq}/audio` | Officers and admins. |
| `GET` and `POST /api/admin/demo-reset` | Admins. |
| `warmed` on each ASR in `/api/health` | So the presenter knows when to start. |

## Phase 5: Supabase readiness and the online presentation (5 November 2026)

The final presentation runs against Supabase from Nairobi, where a round trip takes about 200 ms. Phase 4's reply
made up to 125 of them, or 25 s on the database for the one that pays out.

### Rulings

| Ruling | What it means here |
|---|---|
| A yes at G2 does not satisfy C2 | Kept as built: an income left out at G2 can still be asked about at C2. |
| C5 removed as a question (a later ruling in this phase; it replaced a new wording for it) | See "Guarantors come only from standing pledges" below. |

### What was measured, and how

`tests/latency_demo.py` runs both demo conversations in both languages over HTTP on a scratch database on a local
PostgreSQL 16, through a TCP proxy that counts every time the client waits for the server. That is every statement and
also every BEGIN, COMMIT, ping and statement prepare, which a statement count cannot see, so this figure and not the
request log's is the true cost. The database time adds up, per turn, what each statement really took, with a hook sleeping
200 ms for each, and 200 ms for each round trip the hook cannot see.

| Turn | Round trips, phase 4 | Round trips now | Database time now at 200 ms |
|---|---:|---:|---:|
| Starting the conversation | 17 | 5 | 1.0 to 1.2 s |
| Consent, then G2 | 21 | 4 | 0.8 to 1.0 s |
| G2 answered, then R1 | 18 | 3 | 0.6 to 0.8 s |
| R1 answered, then C1 | 29 | 4 | 0.8 to 1.0 s |
| C1 answered, then CONFIRM or C2 | 28 | 4 | 0.8 to 1.1 s |
| C2 answered, then CONFIRM (Njeri) | 28 | 4 | 0.8 to 1.0 s |
| Yes, paid out: Wanjiru, O1 | 82 | 8 | 1.6 to 1.7 s |
| Yes, offer taken and paid out: Njeri, O2 | 125 | 8 | 1.6 to 1.8 s |
| `/present` conversation poll, changed | 12 | 3 | 0.6 s |
| `/present` conversation poll, nothing moved (304) | 12 | 1 | 0.2 s |
| `/present` list poll | 5 | 2 | 0.4 s |
| Chat stage poll | 6 | 2 | 0.4 s |
| Chat transcript | 13 | 3 | 0.6 s |
| My applications | 6 | 2 | 0.4 s |
| My SACCO (not polled) | 19 | 14 | 2.8 to 2.9 s |

This is the database's share of a turn and nothing else: not the classifier, Gemini, speech, the Paza transcription,
nor the upload of a voice reply to Supabase Storage, which is an HTTP request of its own before Paza runs. Nothing here
has run on Supabase, and 200 ms is an estimate of the path to it. A new connection costs several round trips more (TLS and
SCRAM), at the first request, and on whichever request finds its connection past `pool_recycle` (four minutes).

My SACCO is unchanged but for the sign-in: it is not polled, and the demo need not open it. It is the one screen left
that a member can click on and wait about 3 s for.

### How it got there

| Decision | Reason |
|---|---|
| A reply makes one atomic write, of everything | Member's turn, bot's turns, state, profile confirmation and, if there is one, the decision and the payout. The money and the words announcing it can no longer be parted: **this reverses phase 3's design**, in which a decision committed first and a retry found it by its key. A failure at any point now leaves nothing changed and no money moved; answering again pays once. The idempotency keys are still written and still looked at. |
| `batch.py`: one statement per reply | A decision touches a dozen tables, and each INSERT through the ORM is a round trip. On PostgreSQL the batch is one WITH of one INSERT or UPDATE per table, with no driver feature that could behave differently through Supabase's pooler. Foreign keys are checked at its end. SQLite cannot write inside a WITH, so there it is a statement per table in one transaction, and the same code runs on both. Ids are reserved first, so rows can refer to each other, and an id reserved and not used is skipped, as after a rollback. |
| Speech comes before the write, and the words are chosen before the locks | A pay-out reply evaluates once without locks to choose its words and speak them, then takes the locks and evaluates again on what the database now says. If the answer has changed, nothing is written, the words are chosen again, and the member hears what is true. Nothing is locked while speech is made, on a cold line or a warm one. |
| Row locks kept, in one statement | `ledger.lock_for_decision` takes the same rows in the same order as `lock_members`: members first, lowest id first, then accounts. It is one statement, and it reserves the ids too. What is decided on is read in the next statement, because a statement sees the database as it was when it began, whatever it waited for. |
| One read per evaluation | `decisions.read_snapshot` reads everything `evaluate` needs as one UNION ALL: 13 parts, written to give what the ledger's own functions give, and tested against them. The model reruns only if the features changed. |
| No BEGIN or COMMIT around what does not need them | Under READ COMMITTED a transaction of reads sees nothing a statement alone would not, and one write is atomic by itself, so these run in autocommit: every GET, and a reply up to its write. Only a decision has a transaction. GET handlers that write (the idle sweep, an export's audit row) still commit, one statement at a time. |
| A ping only after 30 s idle, and the newest connection first | `pool_pre_ping` cost a round trip on every checkout. A connection used in the last 30 s is taken as alive, and one idle longer is still pinged and replaced. The price: a connection that dies within those 30 s fails its next request, instead of the ping catching it, and SQLAlchemy then replaces the pool. With `/present` polling, that window is small and a retry works. |
| psycopg's statement prepare is off | On a statement's fifth use it costs a round trip of its own, on each connection, which turned up as two extra on Njeri's payout. It saves the server a little and us nothing. |
| A member's record and profile come with the session | A joined read: one round trip fewer on every member page. |
| The `/present` poll is one statement for sign-in and tag | An ETag covers the conversation, the stage, and anything that changes how it came out: the application, the loan and the number of decisions on it. A browser revalidates by itself (`no-cache`), checked in a real browser: unchanged, its polls come back 304. The poll makes `require_officer`'s refusals itself, in the same words. |

### The demo dataset on PostgreSQL

`seed_demo.py --demo-postgres` refuses, without changing anything, unless it has `--replace-everything-in-this-database`,
DATABASE_URL is PostgreSQL at head, the classifier and the 40 clips are all present, every user has a seed tag, and the host
is typed back. TRUNCATE is stopped on the append-only tables by their own triggers, so it turns those off for its one
transaction, as table owner, needing no superuser. It puts back the `system` user, which `0006` made and nothing else would.

| Decision | Reason |
|---|---|
| The phone pre-flight is still needed | The seeder needs the schema at head, so `0004` runs first, on the rows there now. |
| The clips go in a folder named for the build | `RESTART IDENTITY` reuses interview ids, and the storage backend refuses to overwrite. Earlier clips stay in the bucket, unreferenced, until someone deletes them. |
| A user with no tag stops it | They may be real. Marking the test run's leftovers as disposable is an UPDATE the README gives you to run, after looking at the list. |
| `warm_demo.py` builds its own SQLite from the seed | It no longer needs `data/demo.db`, and cannot reach Supabase. `--source` still copies a file. |

The seed makes about 2,700 statements, so about 10 minutes from Nairobi. It was not worth speeding up for something run once.

### Row-level security

Nothing was missing, so no migration was added: every table, including those from `0004` to `0007` and `alembic_version`, has
RLS on and no policies. `tests/test_postgres.py` now runs a SELECT on every table as a role with SELECT granted, as
Supabase grants anon and authenticated, and gets nothing. `scripts/check_rls.py` lists any table without RLS and any policy open to those roles, for running against Supabase.

### Online presentation

`?stage=1` frames the chat. Presentation mode needed three changes for 960 px: the working stacks into one column, the
verdict stacks, and each turn's four timings go two by two. `tests/browser/online_layout.mjs` measures both in Chromium:
no sideways scrolling and nothing past the window's edge, at 1366x768 and 960x950 and 960x700, with the chat at 390x800. It checks the stage indicator's words are not clipped.

### Kikuyu translation

`scripts/translations.py export` writes `translations/kikuyu.csv`, 194 lines, and `import` reads it back, refusing everything if a slot is missing or extra, or if the English has moved on since.

| Decision | Reason |
|---|---|
| What is on the sheet | Every template, `t.chat`, the Why sentences (reasons, checks, drivers), the Yes and No buttons. |
| What is not | The six strings shown before a language is chosen, and `member_text.py`'s status labels and practice results: those screens have no Kikuyu to switch to, so a translation there would do nothing. |
| `_check_sentence` is now a table of sentences with ids | They were f-strings, which cannot be translated. The English comes out the same; `test_member_text.py` says so. |
| An explanation's reason needs its figures, kept on the turn from now on | The reason was stored as finished English. A turn from before this keeps it. |
| The tap sends the word `lexicon.py` reads, whatever the button says | A translator's wording of Yes must not change what the parser hears. |
| Tests pin the Kikuyu to empty | So that filling in the sheet breaks no test about the wording. `test_translations.py` reads the files as they are. |

### Guarantors come only from standing pledges

Ruling, after the above: C5 is no longer a question. A member is never asked to name anyone. Guarantors come from the
pledges in the database, and policy version `2026.11.4` records decisions made this way.

| When the pledges cannot cover the amount | What happens |
|---|---|
| What they can cover is at least half the request, and within the other maximums | C6: "We can offer up to ...". A yes goes to CONFIRM at that amount, and a yes there pays it out. |
| The member says no to that | Refer, `guarantors_short`: "This loan needs another guarantor; an officer will add one." |
| It is under half the request | The same referral, with no question. |
| Fewer than two pledges have anything free | The same referral, with no question: two guarantors are the SACCO rule at any amount. |
| No pledge at all | "Not now", as before (`no_guarantors`). |

What they can cover is the member's own free deposits plus every free guarantor's capacity, each held to their pledge's
ceiling, and it is on the trace as `maximums.capacity_kes`. The offer is the lowest of that, the 3 x rule and affordability.

| Decision | Reason |
|---|---|
| The reason is the old code, `guarantors_short`, with the ruling's words | A referral for the same fact. `named_guarantor` is gone with what could cause it. |
| An offer above the automatic limit is not made | A yes could only lead to `above_limit`, so that referral comes straight away. "Within the other maximums" is read to include this limit. |
| Medium with nothing that could clear it is not asked | An officer decides whichever way it answers. C3 can still clear it first, and C6 follows. |
| Under half because of the deposits or income is still `offer_too_small` | Another guarantor would not change that. |
| C6 above both maximums keeps `offer_declined` when guarantors are not the limit | Turning it down is a different thing to refer. |
| The lookup is deleted | `named_member`, the extra option, `parse_guarantor`, the `extra_guarantor` answer and `extra_guarantor_found` served C5 alone. The branch and member flows read member numbers in `loans.py`, which this leaves alone. |
| Old records still work | A stored `extra_guarantor` answer is ignored when the engine runs again on a decision (review, or accepting an offer), and stays on the immutable record. A conversation waiting on C5 is closed at startup. |

C6 tells a member a figure that their guarantors' free capacity limits. Over the conversation, with several tries, that is
something about those guarantors' capacity, though only as a total and only within the rate limits. The ruling asks for it,
and it is the first place a member can infer that figure at all.

### API changes for this work

| Change | Reason |
|---|---|
| `extra_guarantor` is no longer an answer (422), and `extra_guarantor_found` is gone from an evaluation; `questions[].id` can no longer be `C5` | The ruling. |
| `ETag` and `304` on `GET /api/present/conversations/{id}` | The poll. |
| `POST /api/conversations/{id}/reply` checks the body before the conversation | The lease is the first look at the conversation. A stranger's reply with a bad body gets 422 rather than 404, which tells them nothing. |
| `reason_values` on the recorded explain | See above. Staff see it; `plain_explain` builds a member's view field by field and it stays out. |
