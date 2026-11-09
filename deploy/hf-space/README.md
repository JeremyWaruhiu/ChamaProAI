---
title: ChamaPro AI
emoji: 🌾
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: other
short_description: Spoken loan conversations for a Kenyan SACCO, Kikuyu and English
startup_duration_timeout: 30m
---

# ChamaPro AI

A SACCO member asks for a loan by talking to a short conversation, in Kikuyu or English, on
their phone; officers see each decision and why. A research prototype from Strathmore
University, shared for academic assessment: see the project's LICENCE (all rights reserved).

**Open the direct address, not this page's embedded view:**
`https://<owner>-<space-name>.hf.space`. Sign-in uses a `SameSite=Strict` session cookie,
which browsers do not set inside the frame that huggingface.co shows the app in (a
different site), so signing in fails there.

## How this Space runs

- CPU only. Kikuyu speech is Microsoft's Paza (Whisper large-v3 turbo), as an OpenVINO INT8
  export on OpenVINO's CPU device; English speech is `openai/whisper-large-v3-turbo` on
  torch, from the public hub. Spoken replies use Meta's MMS voices
  (`facebook/mms-tts-kik`, `facebook/mms-tts-eng`), **CC-BY-NC 4.0: non-commercial use only**.
- The classifier and the Paza export are not in this repo. They are fetched at start from a
  private model repo (`<owner>/chamapro-private`, or `CHAMAPRO_MODEL_REPO`) with `HF_TOKEN`.
- Paza, English Whisper, the classifier and the voices are warmed in the background once
  the API is up, about a minute and a half on 2 vCPUs. The speech cache and anything else
  written at run time go when the Space restarts.
- Data lives in Supabase (PostgreSQL and Storage); the schema must already be at the code's
  migration head, or the API refuses to start and says what to run.

## Secrets (Settings → Variables and secrets → New secret)

| Secret | What |
|---|---|
| `DATABASE_URL` | Supabase **session pooler** connection string |
| `SUPABASE_URL` | `https://<project>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Storage access for interview audio; server side only |
| `SUPABASE_BUCKET` | the private bucket for audio |
| `GEMINI_API_KEY` | extraction and the conversation's language understanding |
| `PILOT_INVITE_CODE` | volunteers' sign-up code; sign-up is off without it |
| `GOOGLE_CLIENT_ID` | "Sign in with Google"; add the `.hf.space` address as an authorised JavaScript origin |
| `HF_TOKEN` | a **read** token that can see the private model repo |

Set in the image (override as Space variables if needed): `ASR_ENGINE=openvino`,
`ASR_DEVICE=CPU`, `ASR_WARM_ENGLISH=1`, `STORAGE_BACKEND=supabase`,
`CONVERSATION_GEMINI_LIVE=1`. `CHAMAPRO_MODEL_REPO` names the private model repo if it is
not `<owner>/chamapro-private`.
