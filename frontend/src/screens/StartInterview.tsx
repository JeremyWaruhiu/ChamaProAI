import { AnimatePresence, m } from 'motion/react'
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, api } from '../api/client'
import type { ApplicantFormOptions, Member } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { Card, DetailList, Field, PageHeader, PracticeBadge, Skeleton, Stepper } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDay, formatKes, parseShillings, todayYmd } from '../lib/format'
import { fadeUp, useReducedMotion } from '../lib/motion'
import { navigate, paths } from '../lib/router'
import {
  EMPTY_WIZARD, STEPS, applicationBody, interviewBody, memberBody, ruleCeiling, stepErrors,
  type Errors, type Step, type WizardDraft,
} from '../lib/wizard'
import { t } from '../strings'
import styles from './StartInterview.module.css'

const W = t.wizard

export function StartInterview({ memberId }: { memberId: number | null }) {
  const reduced = useReducedMotion()
  const [draft, setDraft] = useState<WizardDraft>(EMPTY_WIZARD)
  const [index, setIndex] = useState(0)
  const [tried, setTried] = useState<Partial<Record<Step, boolean>>>({})
  const heading = useRef<HTMLHeadingElement>(null)
  const first = useRef(true)
  const step = STEPS[index]
  const errors = tried[step] ? stepErrors(step, draft) : {}

  const set = useCallback(<K extends keyof WizardDraft>(k: K, v: WizardDraft[K]) => setDraft((d) => ({ ...d, [k]: v })), [])

  // Arriving from a member's page: that member is already chosen.
  useEffect(() => {
    if (!memberId) return
    let live = true
    api.member(memberId).then((m) => { if (live) setDraft((d) => ({ ...d, memberMode: 'existing', member: m })) }, () => {})
    return () => { live = false }
  }, [memberId])

  // Each new step is announced by moving focus to its heading.
  useEffect(() => {
    if (first.current) { first.current = false; return }
    heading.current?.focus()
  }, [index])

  function next(e?: FormEvent) {
    e?.preventDefault()
    const errs = stepErrors(step, draft)
    if (Object.keys(errs).length) {
      setTried((x) => ({ ...x, [step]: true }))
      window.setTimeout(() => document.querySelector<HTMLElement>('[aria-invalid="true"], [data-invalid="true"]')?.focus(), 0)
      return
    }
    setIndex((i) => Math.min(i + 1, STEPS.length - 1))
  }

  const errorCount = Object.keys(errors).length

  return (
    <>
      <PageHeader eyebrow={W.stepOf(index + 1, STEPS.length)} title={W.title} lead={W.lead}
                  badges={draft.mode === 'practice' ? <PracticeBadge /> : undefined} />
      <Stepper steps={W.steps} current={index} label={W.stepper} onStep={setIndex} />

      <form onSubmit={next} noValidate className={styles.form}>
        <AnimatePresence mode="wait" initial={false}>
          <m.div key={step} {...fadeUp(reduced, 0, 10)}>
            <Card>
              <div className={styles.stepHead}>
                <h2 ref={heading} tabIndex={-1} className={styles.stepTitle}>{TITLES[step]}</h2>
                <p className="muted">{LEADS[step]}</p>
              </div>
              {errorCount > 0 && (
                <p className={styles.summary} role="alert"><Icon name="alert" size={18} /> {W.errors.fixBelow(errorCount)}</p>
              )}
              {step === 'member' && <MemberStep draft={draft} set={set} errors={errors} />}
              {step === 'loan' && <LoanStep draft={draft} set={set} errors={errors} />}
              {step === 'applicant' && <ApplicantStep draft={draft} set={set} errors={errors} />}
              {step === 'setup' && <SetupStep draft={draft} set={set} />}
              {step === 'review' && <ReviewStep draft={draft} setDraft={setDraft} goTo={setIndex} />}
            </Card>
          </m.div>
        </AnimatePresence>

        {step !== 'review' && (
          <div className={styles.nav}>
            {index > 0
              ? <button type="button" className="btn btn-secondary" onClick={() => setIndex(index - 1)}>
                  <Icon name="arrowLeft" /> {t.common.back}
                </button>
              : <a className="btn btn-quiet" href={paths.home()}>{t.common.cancel}</a>}
            <button type="submit" className="btn btn-primary btn-large">{t.common.continue} <Icon name="arrowRight" /></button>
          </div>
        )}
        {step === 'review' && (
          <div className={styles.nav}>
            <button type="button" className="btn btn-secondary" onClick={() => setIndex(index - 1)}>
              <Icon name="arrowLeft" /> {t.common.back}
            </button>
          </div>
        )}
      </form>
    </>
  )
}

const TITLES: Record<Step, string> = {
  member: W.memberTitle, loan: W.loanTitle, applicant: W.applicantTitle, setup: W.setupTitle, review: W.reviewTitle,
}
const LEADS: Record<Step, string> = {
  member: W.memberLead, loan: W.loanLead, applicant: W.applicantLead, setup: W.setupLead, review: W.reviewLead,
}

type Setter = <K extends keyof WizardDraft>(k: K, v: WizardDraft[K]) => void
interface StepProps { draft: WizardDraft; set: Setter; errors: Errors }

// --- Step 1: member ---------------------------------------------------------------

function MemberStep({ draft, set, errors }: StepProps) {
  return (
    <div className={styles.fields}>
      <fieldset className={styles.fieldset}>
        <legend className="visually-hidden">{W.memberTitle}</legend>
        <div className={styles.twoChoices}>
          {(['existing', 'new'] as const).map((m) => (
            <label key={m} className="choice">
              <input type="radio" name="memberMode" checked={draft.memberMode === m} onChange={() => set('memberMode', m)} />
              <Icon name={m === 'existing' ? 'search' : 'plus'} />
              <span>{m === 'existing' ? W.existing : W.newMember}</span>
            </label>
          ))}
        </div>
      </fieldset>
      {draft.memberMode === 'existing'
        ? <MemberSearch chosen={draft.member} onChoose={(m) => set('member', m)} error={errors.member} />
        : <NewMemberFields draft={draft} set={set} errors={errors} />}
    </div>
  )
}

function MemberSearch({ chosen, onChoose, error }: { chosen: Member | null; onChoose: (m: Member | null) => void; error?: string }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Member[] | null>(null)
  const [failed, setFailed] = useState<ApiError | null>(null)

  useEffect(() => {
    const term = q.trim()
    // oxlint-disable-next-line react/set-state-in-effect -- clear the results as soon as the search is too short
    if (term.length < 2) { setResults(null); return }
    let live = true
    const id = window.setTimeout(() => {
      api.members(term, 8).then((m) => { if (live) { setResults(m); setFailed(null) } },
        (e) => { if (live) setFailed(e as ApiError) })
    }, 250)
    return () => { live = false; window.clearTimeout(id) }
  }, [q])

  if (chosen) {
    return (
      <div className={styles.chosen}>
        <span className={styles.avatar} aria-hidden>{chosen.full_name.slice(0, 1)}</span>
        <div className={styles.chosenText}>
          <span className="eyebrow">{W.chosen}</span>
          <strong>{chosen.full_name}</strong>
          <span className="subtle small">{chosen.member_no} · {W.joined(formatDay(chosen.joined_on))}</span>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => onChoose(null)}>{W.change}</button>
      </div>
    )
  }
  return (
    <div className={styles.fields}>
      <Field id="member-search" label={W.searchMembers} hint={W.searchHint} error={error}>
        {(p) => <input {...p} className="input" type="search" value={q} autoComplete="off" onChange={(e) => setQ(e.target.value)} />}
      </Field>
      {failed && <ErrorNotice doing={t.members.loadFailed} error={failed} />}
      {results && results.length === 0 && <p className="muted">{W.noMembers}</p>}
      {results && results.length > 0 && (
        <ul className={styles.results} aria-label={t.topbar.members}>
          {results.map((m) => (
            <li key={m.id}>
              <button type="button" className={styles.result} onClick={() => onChoose(m)}>
                <span className={styles.avatar} aria-hidden>{m.full_name.slice(0, 1)}</span>
                <span className={styles.resultText}>
                  <strong>{m.full_name}</strong>
                  <span className="subtle small">{m.member_no} · {W.joined(formatDay(m.joined_on))}</span>
                </span>
                <span className={styles.resultAction}>{W.choose}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function NewMemberFields({ draft, set, errors }: StepProps) {
  const m = draft.newMember
  const put = (k: keyof typeof m, v: string) => set('newMember', { ...m, [k]: v })
  return (
    <div className={styles.grid}>
      <Field id="nm-no" label={W.memberNo} hint={W.memberNoHint} error={errors.member_no}>
        {(p) => <input {...p} className="input" value={m.member_no} maxLength={32} autoComplete="off"
                       onChange={(e) => put('member_no', e.target.value)} />}
      </Field>
      <Field id="nm-name" label={W.fullName} error={errors.full_name}>
        {(p) => <input {...p} className="input" value={m.full_name} maxLength={200} autoComplete="off"
                       onChange={(e) => put('full_name', e.target.value)} />}
      </Field>
      <Field id="nm-phone" label={W.phone} hint={W.phoneHint} error={errors.phone} optional>
        {(p) => <input {...p} className="input" type="tel" inputMode="tel" value={m.phone} autoComplete="off"
                       onChange={(e) => put('phone', e.target.value)} />}
      </Field>
      <Field id="nm-joined" label={W.joinedOn} hint={W.joinedHint} error={errors.joined_on}>
        {(p) => <input {...p} className="input" type="date" value={m.joined_on} max={todayYmd()}
                       onChange={(e) => put('joined_on', e.target.value)} />}
      </Field>
      <p className={`${styles.wide} subtle small`}><Icon name="lock" size={14} /> {W.noIdNote}</p>
    </div>
  )
}

// --- Step 2: loan ---------------------------------------------------------------------

function LoanStep({ draft, set, errors }: StepProps) {
  const amount = parseShillings(draft.amount)
  const savings = parseShillings(draft.savings)
  const ceiling = savings !== null ? ruleCeiling(savings) : null
  return (
    <div className={styles.grid}>
      <Field id="loan-amount" label={W.amount} error={errors.amount}>
        {(p) => <input {...p} className="input num" inputMode="numeric" value={draft.amount} autoComplete="off"
                       onChange={(e) => set('amount', e.target.value)} />}
      </Field>
      <Field id="loan-term" label={W.term} error={errors.term}>
        {(p) => <input {...p} className="input num" inputMode="numeric" value={draft.term} maxLength={3} autoComplete="off"
                       onChange={(e) => set('term', e.target.value.replace(/\D/g, ''))} />}
      </Field>
      <div className={styles.wide}>
        <Field id="loan-purpose" label={W.purpose} hint={W.purposeHint} error={errors.purpose}>
          {(p) => <input {...p} className="input" value={draft.purpose} maxLength={500} onChange={(e) => set('purpose', e.target.value)} />}
        </Field>
      </div>
      <div className={styles.wide}>
        <Field id="loan-savings" label={W.savings} hint={W.savingsHint} error={errors.savings}>
          {(p) => <input {...p} className="input num" inputMode="numeric" value={draft.savings} autoComplete="off"
                         onChange={(e) => set('savings', e.target.value)} />}
        </Field>
      </div>
      {ceiling !== null && (
        <div className={styles.wide} aria-live="polite">
          {amount !== null && amount > ceiling
            ? <Notice tone="warning">{W.overCeiling(ceiling)}</Notice>
            : <p className={styles.ceiling}><Icon name="scale" size={18} /> {W.ceiling(ceiling)}</p>}
        </div>
      )}
    </div>
  )
}

// --- Step 3: applicant form ---------------------------------------------------------------

function ApplicantStep({ draft, set, errors }: StepProps) {
  const load = useCallback(() => api.applicantForm(), [])
  const { data: options, error, reload } = useLoad<ApplicantFormOptions>(load)
  if (error) return <ErrorNotice doing={t.wizard.failedInterview} error={error} onRetry={reload} />
  if (!options) return <div className={styles.grid} role="status" aria-label={t.app.loading(W.applicantTitle)}>
    <Skeleton height={48} /><Skeleton height={48} /><Skeleton height={48} /><Skeleton height={48} />
  </div>
  return (
    <div className={styles.grid}>
      <Field id="ap-age" label={W.age} error={errors.age}>
        {(p) => <input {...p} className="input num" inputMode="numeric" value={draft.age} maxLength={3} autoComplete="off"
                       onChange={(e) => set('age', e.target.value.replace(/\D/g, ''))} />}
      </Field>
      <fieldset className={styles.fieldset} aria-describedby={errors.sex ? 'ap-sex-error' : undefined}>
        <legend className="field-label">{W.sex}</legend>
        <div className={styles.twoChoices}>
          {options.sex.map((o, i) => (
            <label key={o.value} className="choice">
              <input type="radio" name="sex" value={o.value} checked={draft.sex === o.value}
                     data-invalid={errors.sex && i === 0 ? 'true' : undefined} onChange={() => set('sex', o.value)} />
              <span>{o.label}</span>
            </label>
          ))}
        </div>
        {errors.sex && <p id="ap-sex-error" className="field-error">{errors.sex}</p>}
      </fieldset>
      <div className={styles.wide}>
        <Field id="ap-education" label={W.education} error={errors.education}>
          {(p) => (
            <select {...p} className="select" value={draft.education} onChange={(e) => set('education', e.target.value)}>
              <option value="">{W.choosePlaceholder}</option>
              {options.education.map((o) => <option key={o.value} value={String(o.value)}>{o.label}</option>)}
            </select>
          )}
        </Field>
      </div>
      <div className={styles.wide}>
        <Field id="ap-marital" label={W.marital} error={errors.marital}>
          {(p) => (
            <select {...p} className="select" value={draft.marital}
                    onChange={(e) => set('marital', e.target.value as WizardDraft['marital'])}>
              <option value="">{W.choosePlaceholder}</option>
              {options.marital_status.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </Field>
      </div>
    </div>
  )
}

// --- Step 4: language and mode ----------------------------------------------------------------

function SetupStep({ draft, set }: Omit<StepProps, 'errors'>) {
  return (
    <div className={styles.fields}>
      <fieldset className={styles.fieldset}>
        <legend className="field-label">{W.language}</legend>
        <div className={styles.twoChoices}>
          <BigChoice name="language" checked={draft.language === 'kik'} onChange={() => set('language', 'kik')}
                     title={t.common.kikuyu} hint={W.kikuyuHint} />
          <BigChoice name="language" checked={draft.language === 'en'} onChange={() => set('language', 'en')}
                     title={t.common.english} hint={W.englishHint} />
        </div>
      </fieldset>
      <fieldset className={styles.fieldset}>
        <legend className="field-label">{W.mode}</legend>
        <div className={styles.twoChoices}>
          <BigChoice name="mode" checked={draft.mode === 'live'} onChange={() => set('mode', 'live')}
                     title={W.live} hint={W.liveHint} />
          <BigChoice name="mode" checked={draft.mode === 'practice'} onChange={() => set('mode', 'practice')}
                     title={<>{W.practice} <PracticeBadge /></>} hint={W.practiceHint} />
        </div>
      </fieldset>
    </div>
  )
}

function BigChoice({ name, checked, onChange, title, hint }: {
  name: string; checked: boolean; onChange: () => void; title: ReactNode; hint: string
}) {
  return (
    <label className={`choice ${styles.bigChoice}`}>
      <input type="radio" name={name} checked={checked} onChange={onChange} />
      <span className={styles.bigChoiceText}>
        <span className={styles.bigChoiceTitle}>{title}</span>
        <span className="subtle small">{hint}</span>
      </span>
    </label>
  )
}

// --- Step 5: review and begin -------------------------------------------------------------------

function ReviewStep({ draft, setDraft, goTo }: {
  draft: WizardDraft; setDraft: (f: (d: WizardDraft) => WizardDraft) => void; goTo: (i: number) => void
}) {
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<{ doing: string; error: ApiError } | null>(null)
  const [interviewId, setInterviewId] = useState<number | null>(null)
  const optionsLoad = useCallback(() => api.applicantForm(), [])
  const { data: options } = useLoad(optionsLoad)
  const label = <T extends string | number>(list: { value: T; label: string }[] | undefined, v: string) =>
    list?.find((o) => String(o.value) === v)?.label ?? v

  const memberName = draft.memberMode === 'existing' ? draft.member?.full_name ?? '' : draft.newMember.full_name.trim()
  const edit = (i: number) => (
    <button type="button" className="btn btn-quiet btn-sm" onClick={() => goTo(i)}><Icon name="edit" size={16} /> {t.common.edit}</button>
  )

  // Each part is created once: a retry carries on from the part that failed.
  async function begin() {
    if (Object.keys(stepErrors('review', draft)).length) return
    setBusy(true)
    setFailure(null)
    let member = draft.member
    let doing = W.failedMember
    try {
      if (draft.memberMode === 'new' || !member) {
        member = await api.createMember(memberBody(draft.newMember))
        const created = member
        setDraft((d) => ({ ...d, memberMode: 'existing', member: created }))
      }
      doing = W.failedInterview
      let ivId = interviewId
      if (ivId === null) {
        ivId = (await api.createInterview(interviewBody(draft, member.full_name))).id
        setInterviewId(ivId)
      }
      doing = W.failedApplication
      await api.createApplication(applicationBody(draft, member.id, ivId))
      navigate(paths.record(ivId, 1))
    } catch (e) {
      setFailure({ doing, error: e instanceof ApiError ? e : new ApiError(0, String(e)) })
      setBusy(false)
    }
  }

  const amount = parseShillings(draft.amount) ?? 0
  return (
    <div className={styles.fields}>
      <div className={styles.reviewGrid}>
        <section className={styles.reviewBlock}>
          <div className={styles.reviewHead}><h3>{W.member}</h3>{edit(0)}</div>
          <p>{draft.memberMode === 'new'
            ? W.newMemberSummary(draft.newMember.full_name.trim(), draft.newMember.member_no.trim())
            : `${draft.member?.full_name} (${draft.member?.member_no})`}</p>
        </section>
        <section className={styles.reviewBlock}>
          <div className={styles.reviewHead}><h3>{W.loan}</h3>{edit(1)}</div>
          <DetailList items={[
            [W.reviewAmount, W.loanSummary(amount, Number(draft.term))],
            [W.reviewPurpose, draft.purpose.trim()],
            [W.reviewSavings, formatKes(parseShillings(draft.savings) ?? 0)],
          ]} />
        </section>
        <section className={styles.reviewBlock}>
          <div className={styles.reviewHead}><h3>{W.applicant}</h3>{edit(2)}</div>
          <p>{W.applicantSummary(draft.age, label(options?.sex, draft.sex), label(options?.education, draft.education),
            label(options?.marital_status, draft.marital))}</p>
        </section>
        <section className={styles.reviewBlock}>
          <div className={styles.reviewHead}><h3>{W.interview}</h3>{edit(3)}</div>
          <p className={styles.inline}>
            {draft.language === 'kik' ? t.common.kikuyu : t.common.english} ·{' '}
            {draft.mode === 'practice' ? <>{W.practice} <PracticeBadge /></> : W.live}
          </p>
        </section>
      </div>
      {failure && <ErrorNotice doing={failure.doing} error={failure.error} onRetry={begin} />}
      <button type="button" className="btn btn-accent btn-large btn-block" onClick={begin} disabled={busy || !memberName}
              aria-busy={busy || undefined}>
        {busy ? <span className="spinner" aria-hidden /> : <Icon name="mic" />}
        {busy ? W.beginning : W.begin}
      </button>
    </div>
  )
}
