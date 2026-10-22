# Design changes: dashboard vs wireframes (Figures 4.8–4.12)

The Sprint II dashboard (`frontend/`) follows the wireframes in
`docs/wireframes/` for screen structure and flow. This file records every
place where it differs, whether something was added, changed or deferred, with
a one-line reason. Wireframe figure numbers refer to Chapter 4.

## Across all screens

| Change | Status | Reason |
|---|---|---|
| Interview screens share a step bar (Record answers · Review transcripts · Assessment) and a "← All interviews" link | Added | The wireframes show the screens separately; officers need a visible, one-tap way between the three steps of one interview. |
| Risk classes use colour (green / amber / red) as well as text | Changed | The wireframes are monochrome; colour speeds recognition, and the text label means it never relies on colour alone. |
| System fonts only, no web fonts | Changed | Rural branches may be offline or on slow links; nothing is fetched from the internet. |
| Status words are plain language ("Waiting", "Transcribing", "Transcribed", "Not transcribed") | Changed | Officers have basic computer literacy; "queued" and "failed" are system terms. |
| Interview questions grouped by the eight domains recorded in `data/manifest.csv`, not Table 3.1's domains | Changed | The 40 recorded responses use the manifest's domains (Household, Chama, …); Table 3.1's set (Social Capital, Character & Attitude) has no recordings. |
| A request that gets no answer within 15 seconds (90 s for the assessment) shows an error with a Retry button | Added | The wireframes show no failure states; a stalled server must never leave a screen spinning forever. |

## Figure 4.8 — Login

| Change | Status | Reason |
|---|---|---|
| No login screen, no officer name in the header | Deferred (Sprint III) → **Implemented** | Authentication and role separation are now in place: a sign-in page at `#/login`, cookie sessions (8 h), officer and admin roles, and the signed-in username, role and Sign out in every screen's header. Only admins see and may open Model & Evaluation. |
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
| Columns: applicant, date, answers recorded out of 40, status, risk class | Changed | Specified for Sprint II; shows recording progress, which the wireframe's single badge could not. |
| "PROCESSING" badge replaced by a status column ("Transcribing answers", "Ready for review", "Decision: …") | Changed | Status and risk class are different facts; mixing them in one badge hid which step an interview is at. |
| Officer's decision shown in the status column | Added | The list should show whether a decision has been recorded, not only the model's class. |
| Opening an interview goes to its next step (record, review or assessment) | Added | Saves the officer finding where they left off. |
| Search by name or member number | Deferred | Not needed at Sprint II volumes; needs the applicant register. |
| Member numbers (M-0412) | Deferred | No member register yet. |
| Pagination | Deferred | Not needed at Sprint II volumes. |
| New interview opens an inline form for the applicant's name | Added | The wireframe shows the button but not what follows; the name is optional so an interview can start at once. |

## Figure 4.10 — Interview recording

| Change | Status | Reason |
|---|---|---|
| One question per screen with Previous / Next | Kept | As in the wireframe. |
| Kikuyu question text with English gloss beneath | Kept, with fallback | The Kikuyu wording is still being corrected by a native speaker; where it is missing the English is shown alone. |
| Questions are a draft (`docs/interview_questions.txt`) | Changed | No 40-question instrument existed; one question per scripted answer was drafted from Table 3.1's wording, pending review. |
| Record answer, Stop, Replay, Re-record | Kept | As in the wireframe; Replay plays the stored clip from the server. |
| Upload a recording | Added | Specified; lets an officer use a phone recording when the laptop microphone fails. |
| Live status badge per answer (Waiting, Transcribing, Transcribed, Not transcribed) with a calm waiting message and estimate | Added | Transcription takes about 35 s per clip on CPU; the officer must see that waiting is normal and can carry on. |
| Re-record while transcribing waits and retries automatically | Added | The server refuses to delete a clip mid-transcription (409, Retry-After); the dashboard waits rather than showing an error. |
| Domain progress segments are tappable; question number buttons for the current domain | Added | Lets the officer return to any answer without stepping through every screen. |
| Live waveform | Deferred | Not needed to record or check an answer; Replay covers verification. |
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
| Synchronised playback bar | Changed | Replaced by a Replay button per answer; each answer is a separate 3–10 s clip. |
| Shaded low-confidence spans and the "ASR confidence" figure | Deferred | The ASR stage does not produce per-word confidence yet. |
| Flag for supervisor | Deferred | Officer and admin roles now exist; the flag itself and a supervisor's queue are still to be built. |
| "Confirm and extract features" → "Run assessment", with a confirmation step | Changed | One plain action; the confirmation is there because an assessment can never be changed afterwards. |
| Run assessment disabled until nothing is waiting or transcribing, and until corrections are saved | Added | Specified for transcription; unsaved corrections would otherwise be silently left out. |
| Read-only once assessed | Added | Specified; assessments are immutable. |

## Figure 4.12 — Credit assessment

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
| Model, extraction model and classifier hash stored with each assessment, not shown on screen | Added | Auditability (Chapter 4): the stored record identifies exactly which model produced it; the footer line was removed from the screen as clutter for officers. |
| Approve at a reduced amount | Deferred | Needs the loan amount, which is not captured yet. |
| Loan amount requested in the header | Deferred | Not captured by the interview yet. |
| SACCO baseline (savings multiplier) and divergence panel | Deferred | Needs savings and guarantor records from the SACCO's system. |
| Export report | Deferred | Not needed for Sprint II; the assessment is stored and viewable. |
| Storing the repayment outcome for retraining | Deferred | Needs loan servicing data after disbursement. |

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
