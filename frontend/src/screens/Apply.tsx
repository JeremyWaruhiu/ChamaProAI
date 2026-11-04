import { useCallback, useRef, useState, type FormEvent } from 'react'
import { ApiError, api } from '../api/client'
import type { ApplyOptions, MyMember } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { SlotPicker } from '../components/SlotPicker'
import { Badge, Card, Field, PageHeader, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { EMPTY_APPLY, applyErrors, applyWarnings, ruleLimit, savingsFor, toApplicationBody, type ApplyDraft } from '../lib/apply'
import { formatDay, formatKes } from '../lib/format'
import { navigate, paths } from '../lib/router'
import { t } from '../strings'
import styles from './Apply.module.css'

const A = t.apply

export function Apply() {
  const load = useCallback(() => Promise.all([api.myMember(), api.applyOptions()]), [])
  const { data, error, reload } = useLoad(load)
  if (error) {
    return error.status === 404
      ? <Notice tone="warning" title={A.title}>{A.notLinked}</Notice>
      : <ErrorNotice doing={A.loadFailed} error={error} onRetry={reload} />
  }
  if (!data) return <SkeletonPage what={A.title} />
  return <>
    <PageHeader title={A.title} lead={A.lead} />
    <ApplyForm member={data[0]} options={data[1]} />
  </>
}

export function ApplyForm({ member, options }: { member: MyMember; options: ApplyOptions }) {
  const [d, setD] = useState<ApplyDraft>(EMPTY_APPLY)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const summary = useRef<HTMLParagraphElement>(null)
  const errors = tried ? applyErrors(d, member, options.max_term_months) : {}
  const count = Object.keys(errors).length
  const put = <K extends keyof ApplyDraft>(k: K, v: ApplyDraft[K]) => setD((x) => ({ ...x, [k]: v }))

  const limit = ruleLimit(d, member, options.savings_multiplier)
  const warnings = applyWarnings(d, member, options.savings_multiplier, options.min_tenure_months)
  const savings = savingsFor(d, member)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (Object.keys(applyErrors(d, member, options.max_term_months)).length) {
      window.setTimeout(() => summary.current?.focus(), 0)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const app = await api.apply(toApplicationBody(d, member))
      navigate(paths.myApplication(app.id))
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate aria-label={A.title}>
      <Card title={A.yourDetails}>
        <p className="subtle small">{A.readOnlyNote}</p>
        <div className={styles.readOnly}>
          <ReadOnly id="ap-name" label={A.fullName} value={member.full_name} />
          <ReadOnly id="ap-no" label={A.memberNo} value={member.member_no} />
          <ReadOnly id="ap-phone" label={A.phone} value={member.phone ?? A.noPhone} />
          <ReadOnly id="ap-tenure" label={A.tenure} value={A.tenureValue(member.tenure_months, formatDay(member.joined_on))} />
          {member.savings_kes !== null && <ReadOnly id="ap-savings" label={A.savings} value={formatKes(member.savings_kes)} />}
        </div>
        {member.savings_kes !== null && (
          <p className={styles.savingsStatus}>
            <span className="subtle small">{A.savingsVerification}:</span>{' '}
            <Badge tone={member.savings_status === 'verified' ? 'low' : 'wait'}
                   icon={member.savings_status === 'verified' ? 'check' : 'clock'}>{t.savingsStatus[member.savings_status]}</Badge>
          </p>
        )}
        {member.savings_kes === null && (
          <div className={styles.declare}>
            <Field id="ap-declare" label={A.declareSavings} hint={A.declareHint} error={errors.savings}>
              {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={d.savings}
                             onChange={(e) => put('savings', e.target.value)} />}
            </Field>
          </div>
        )}
      </Card>

      <Card title={A.theLoan} delay={0.05}>
        <div className={styles.fields}>
          <Field id="ap-amount" label={A.amount}
                 hint={limit !== null && savings !== null ? A.limitHint(limit, options.savings_multiplier) : A.limitUnknown}
                 error={errors.amount}>
            {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={d.amount}
                           onChange={(e) => put('amount', e.target.value)} />}
          </Field>
          {warnings.map((w) => <Notice key={w} tone="warning">{w}</Notice>)}
          <Field id="ap-purpose" label={A.purpose} error={errors.purpose}>
            {(p) => (
              <select {...p} className="select" value={d.purpose} onChange={(e) => put('purpose', e.target.value)}>
                <option value="">{A.choose}</option>
                {options.purposes.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
          </Field>
          {d.purpose === 'Other' && (
            <Field id="ap-other" label={A.purposeOther} error={errors.purposeOther}>
              {(p) => <input {...p} className="input" maxLength={500} value={d.purposeOther}
                             onChange={(e) => put('purposeOther', e.target.value)} />}
            </Field>
          )}
          <Field id="ap-term" label={A.term} error={errors.term}>
            {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={d.term}
                           onChange={(e) => put('term', e.target.value)} />}
          </Field>
        </div>
      </Card>

      <Card title={A.interview} delay={0.1}>
        <div className={styles.fields}>
          <fieldset className={styles.fieldset}>
            <legend className="field-label">{A.language}</legend>
            <div className={styles.choices}>
              {(['kik', 'en'] as const).map((l) => (
                <label key={l} className="choice">
                  <input type="radio" name="ap-language" checked={d.language === l} onChange={() => put('language', l)} />
                  <span>{l === 'kik' ? t.common.kikuyu : t.common.english}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <SlotPicker date={d.date} time={d.time} idPrefix="ap" errorDate={errors.date} errorTime={errors.time}
                      onChange={(next) => setD((x) => ({ ...x, ...next }))} />
        </div>
      </Card>

      <Card title={A.applicant} delay={0.15}>
        {member.applicant_complete ? (
          <>
            <p className="subtle small">{A.applicantKnown}</p>
            <div className={styles.readOnly}>
              <ReadOnly id="ap-age" label={A.age} value={String(member.age)} />
              <ReadOnly id="ap-sex" label={A.sex} value={labelOf(options.sex, member.sex)} />
              <ReadOnly id="ap-edu" label={A.education} value={labelOf(options.education, member.education)} />
              <ReadOnly id="ap-mar" label={A.marital} value={labelOf(options.marital_status, member.marital_status)} />
            </div>
          </>
        ) : (
          <>
            <p className="subtle small">{A.applicantNew}</p>
            <ApplicantFields d={d} options={options} errors={errors} put={put} />
          </>
        )}
      </Card>

      {count > 0 && <p ref={summary} tabIndex={-1} className={styles.summary} role="alert"><Icon name="alert" size={18} /> {A.fixErrors(count)}</p>}
      {error && <ErrorNotice doing={A.failed} error={error} />}
      <button type="submit" className="btn btn-primary btn-large btn-block" disabled={busy} aria-busy={busy || undefined}>
        {busy && <span className="spinner" aria-hidden />} {busy ? A.submitting : A.submit}
      </button>
    </form>
  )
}

const labelOf = (options: { value: string | number; label: string }[], value: string | number | null) =>
  options.find((o) => o.value === value)?.label ?? String(value ?? '')

function ReadOnly({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      <input id={id} className="input" value={value} readOnly aria-readonly />
    </div>
  )
}

export function ApplicantFields({ d, options, errors, put }: {
  d: Pick<ApplyDraft, 'age' | 'sex' | 'education' | 'marital'>
  options: Pick<ApplyOptions, 'sex' | 'education' | 'marital_status'>
  errors: Partial<Record<'age' | 'sex' | 'education' | 'marital', string>>
  put: <K extends 'age' | 'sex' | 'education' | 'marital'>(k: K, v: ApplyDraft[K]) => void
}) {
  return (
    <div className={styles.fieldsTwo}>
      <Field id="ap-age" label={A.age} error={errors.age}>
        {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={d.age}
                       onChange={(e) => put('age', e.target.value)} />}
      </Field>
      <Field id="ap-sex" label={A.sex} error={errors.sex}>
        {(p) => (
          <select {...p} className="select" value={d.sex} onChange={(e) => put('sex', e.target.value as ApplyDraft['sex'])}>
            <option value="">{A.choose}</option>
            {options.sex.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
      </Field>
      <Field id="ap-edu" label={A.education} error={errors.education}>
        {(p) => (
          <select {...p} className="select" value={d.education} onChange={(e) => put('education', e.target.value)}>
            <option value="">{A.choose}</option>
            {options.education.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
      </Field>
      <Field id="ap-mar" label={A.marital} error={errors.marital}>
        {(p) => (
          <select {...p} className="select" value={d.marital} onChange={(e) => put('marital', e.target.value as ApplyDraft['marital'])}>
            <option value="">{A.choose}</option>
            {options.marital_status.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
      </Field>
    </div>
  )
}
