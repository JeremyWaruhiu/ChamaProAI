import { useCallback, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, api } from '../api/client'
import type {
  AccountOut, ApplicantFormOptions, EntryType, LoanOut, MaritalStatus, PledgeOut, ProfileBody, ProfileOut, SaccoView, Sex,
} from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice, Notice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, EmptyState, Field, Modal, PageHeader, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatDay, formatKes, todayYmd } from '../lib/format'
import { navigate, paths } from '../lib/router'
import {
  EMPTY_PROFILE, FLAG_KEYS, profileErrors, profileToDraft, toProfileBody, type FlagGroup, type ProfileDraft,
} from '../lib/profile'
import { t } from '../strings'
import styles from './MySacco.module.css'

const S = t.sacco

// --- The member's page ---------------------------------------------------------------------

export function MySacco() {
  const load = useCallback(() => Promise.all([api.mySacco(), api.applyOptions()]), [])
  const { data, error, reload, setData } = useLoad(load)
  const [editing, setEditing] = useState(false)
  const toast = useToast()
  if (error) {
    return error.status === 404
      ? <Notice tone="warning" title={S.title}>{S.notLinked}</Notice>
      : <ErrorNotice doing={S.loadFailed} error={error} onRetry={reload} />
  }
  if (!data) return <SkeletonPage what={S.title} />
  const [view, options] = data

  async function confirm() {
    try {
      setData([await api.confirmProfile(), options])
      toast(S.confirmed)
    } catch (e) {
      toast((e as ApiError).message, 'error')
    }
  }

  return (
    <>
      <PageHeader title={S.title} lead={S.lead} />
      <SaccoPanels view={view} options={options} onView={(next) => setData([next, options])} actions={
        <>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setEditing(true)}>
            <Icon name="edit" size={16} /> {S.requestChange}
          </button>
          {view.profile.confirmed_at && (
            <button type="button" className="btn btn-quiet btn-sm" onClick={confirm}><Icon name="check" size={16} /> {S.stillRight}</button>
          )}
        </>
      } />
      {editing && (
        <Modal open title={S.editTitle} onClose={() => setEditing(false)}>
          <p className="muted small">{S.editLead}</p>
          <ProfileForm initial={profileToDraft(view.profile)} options={options} submit={S.sendChange} failed={S.editFailed}
                       onSubmit={async (body) => {
                         setData([await api.editProfile(body), options])
                         toast(S.changeSaved)
                         setEditing(false)
                       }} />
        </Modal>
      )}
    </>
  )
}

// --- The form, once after sign-up ------------------------------------------------------------

export function Registration() {
  const load = useCallback(() => api.applyOptions(), [])
  const { data: options, error, reload } = useLoad(load)
  if (error) return <ErrorNotice doing={S.loadFailed} error={error} onRetry={reload} />
  if (!options) return <SkeletonPage what={S.registerTitle} />
  return (
    <>
      <PageHeader title={S.registerTitle} lead={S.registerLead} />
      <div className="card">
        <div className={styles.registerBody}>
          <ProfileForm initial={EMPTY_PROFILE} options={options} submit={S.registerSubmit} failed={S.registerFailed}
                       onSubmit={async (body) => {
                         await api.registerProfile(body)
                         navigate(paths.mySacco())
                       }} />
          <a href={paths.my()} className={styles.skip}>{S.registerSkip}</a>
        </div>
      </div>
    </>
  )
}

export function ProfileForm({ initial, options, submit, failed, onSubmit }: {
  initial: ProfileDraft; options: ApplicantFormOptions; submit: string; failed: string
  onSubmit: (body: ProfileBody) => Promise<void>
}) {
  const [d, setD] = useState(initial)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const errors = tried ? profileErrors(d) : {}
  const put = <K extends keyof ProfileDraft>(k: K, v: ProfileDraft[K]) => setD((x) => ({ ...x, [k]: v }))
  const toggle = (group: FlagGroup, key: string) =>
    setD((x) => ({ ...x, [group]: { ...x[group], [key]: !x[group][key] } }))

  async function send(e: FormEvent) {
    e.preventDefault()
    setTried(true)
    if (Object.keys(profileErrors(d)).length) return
    setBusy(true)
    setError(null)
    try {
      await onSubmit(toProfileBody(d))
    } catch (err) {
      setError(err as ApiError)
      setBusy(false)
    }
  }

  const number = (key: 'household_size' | 'children' | 'children_under5' | 'children_in_school' | 'monthly_income_kes' | 'agri_income_kes') => (
    <Field id={`pf-${key}`} label={S.fields[key]} optional error={errors[key]}>
      {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={d[key]}
                     onChange={(e) => put(key, e.target.value)} />}
    </Field>
  )
  const flags = (group: FlagGroup) => (
    <fieldset className={styles.flags}>
      <legend className="field-label">{S.fields[group]}</legend>
      {FLAG_KEYS[group].map((key) => (
        <label key={key} className="choice">
          <input type="checkbox" checked={!!d[group][key]} onChange={() => toggle(group, key)} />
          <span>{S.flags[group][key as keyof typeof S.flags[typeof group]]}</span>
        </label>
      ))}
    </fieldset>
  )

  return (
    <form className={styles.form} onSubmit={send} noValidate aria-label={S.formLabel}>
      <section className={styles.part}>
        <h2 className={styles.partTitle}>{S.groups.personal}</h2>
        <Field id="pf-born" label={S.fields.date_of_birth} optional error={errors.date_of_birth}>
          {(p) => <input {...p} className="input" type="date" max={todayYmd()} value={d.date_of_birth}
                         onChange={(e) => put('date_of_birth', e.target.value)} />}
        </Field>
        <Field id="pf-sex" label={S.fields.sex} optional>
          {(p) => (
            <select {...p} className="select" value={d.sex} onChange={(e) => put('sex', e.target.value as Sex | '')}>
              <option value="">{S.choose}</option>
              {options.sex.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </Field>
        <Field id="pf-education" label={S.fields.education} optional>
          {(p) => (
            <select {...p} className="select" value={d.education} onChange={(e) => put('education', e.target.value)}>
              <option value="">{S.choose}</option>
              {options.education.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </Field>
        <Field id="pf-marital" label={S.fields.marital_status} optional>
          {(p) => (
            <select {...p} className="select" value={d.marital_status}
                    onChange={(e) => put('marital_status', e.target.value as MaritalStatus | '')}>
              <option value="">{S.choose}</option>
              {options.marital_status.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          )}
        </Field>
      </section>
      <section className={styles.part}>
        <h2 className={styles.partTitle}>{S.groups.household}</h2>
        {number('household_size')}
        {number('children')}
        {number('children_under5')}
        {number('children_in_school')}
      </section>
      <section className={styles.part}>
        <h2 className={styles.partTitle}>{S.groups.income}</h2>
        {number('monthly_income_kes')}
        {number('agri_income_kes')}
        {flags('income_sources')}
      </section>
      <section className={styles.part}>
        <h2 className={styles.partTitle}>{S.groups.assets}</h2>
        {flags('non_monetary_savings')}
        {flags('purchases_last_12m')}
      </section>
      <section className={styles.part}>
        <h2 className={styles.partTitle}>{S.groups.credit}</h2>
        <Field id="pf-chama" label={S.fields.chama_loan_use} optional>
          {(p) => (
            <select {...p} className="select" value={d.chama_loan_use} onChange={(e) => put('chama_loan_use', e.target.value)}>
              <option value="">{S.choose}</option>
              {S.chamaUse.map((label, i) => <option key={label} value={i}>{label}</option>)}
            </select>
          )}
        </Field>
        <Field id="pf-lost" label={S.fields.lost_as_guarantor_chama} optional>
          {(p) => (
            <select {...p} className="select" value={d.lost_as_guarantor_chama}
                    onChange={(e) => put('lost_as_guarantor_chama', e.target.value)}>
              <option value="">{S.choose}</option>
              <option value="0">{t.common.no}</option>
              <option value="1">{t.common.yes}</option>
            </select>
          )}
        </Field>
      </section>
      {error && <ErrorNotice doing={failed} error={error} />}
      <button type="submit" className="btn btn-primary btn-block" disabled={busy} aria-busy={busy || undefined}>
        {busy && <span className="spinner" aria-hidden />} {submit}
      </button>
    </form>
  )
}

// --- What the member and the officer both read --------------------------------------------------

export function SaccoPanels({ view, options, staff = false, actions, onView }: {
  view: SaccoView; options: ApplicantFormOptions; staff?: boolean; actions?: ReactNode; onView?: (view: SaccoView) => void
}) {
  return (
    <div className={styles.panels}>
      {!staff && view.notices?.length > 0 && (
        <Card title={S.notices}>
          <ul className={styles.notices}>
            {view.notices.map((n) => (
              <li key={n.id}>{n.text}<span className={styles.entryDate}>{formatDate(n.created_at)}</span></li>
            ))}
          </ul>
        </Card>
      )}
      <ProfileCard profile={view.profile} options={options} staff={staff} actions={actions} />
      <Card title={S.balances} delay={0.03}>
        <ul className={styles.accounts}>{view.accounts.map((a) => <Account key={a.kind} account={a} />)}</ul>
      </Card>
      <Guarantors view={view} staff={staff} onView={onView} />
      <LoanHistory loans={view.loans} />
    </div>
  )
}

function ProfileCard({ profile: p, options, staff, actions }: {
  profile: ProfileOut; options: ApplicantFormOptions; staff: boolean; actions?: ReactNode
}) {
  const label = (list: { value: string | number; label: string }[], v: string | number | null | undefined) =>
    list.find((o) => o.value === v)?.label ?? blank(v)
  const flagged = (group: FlagGroup, value: Record<string, number> | null | undefined) => {
    if (!value) return S.notGiven
    const on = FLAG_KEYS[group].filter((k) => value[k])
    return on.length ? on.map((k) => S.flags[group][k as keyof typeof S.flags[typeof group]]).join(', ') : t.common.none
  }
  const rows: [string, ReactNode][] = [
    [S.fields.date_of_birth, p.date_of_birth ? `${formatDay(p.date_of_birth)} (${S.ageYears(p.age!)})` : p.age ? S.ageYears(p.age) : S.notGiven],
    [S.fields.sex, label(options.sex, p.sex)],
    [S.fields.education, label(options.education, p.education)],
    [S.fields.marital_status, label(options.marital_status, p.marital_status)],
    [S.fields.household_size, blank(p.household_size)],
    [S.fields.children, blank(p.children)],
    [S.fields.children_under5, blank(p.children_under5)],
    [S.fields.children_in_school, blank(p.children_in_school)],
    [S.fields.monthly_income_kes, p.monthly_income_kes == null ? S.notGiven : formatKes(p.monthly_income_kes)],
    [S.fields.agri_income_kes, p.agri_income_kes == null ? S.notGiven : formatKes(p.agri_income_kes)],
    [S.fields.income_sources, flagged('income_sources', p.income_sources)],
    [S.fields.non_monetary_savings, flagged('non_monetary_savings', p.non_monetary_savings)],
    [S.fields.purchases_last_12m, flagged('purchases_last_12m', p.purchases_last_12m)],
    [S.fields.chama_loan_use, p.chama_loan_use == null ? S.notGiven : S.chamaUse[p.chama_loan_use]],
    [S.fields.lost_as_guarantor_chama, p.lost_as_guarantor_chama == null ? S.notGiven : p.lost_as_guarantor_chama ? t.common.yes : t.common.no],
  ]
  const groups = Object.entries(p.groups).filter(([, g]) => g.source)
  const missing = staff ? Object.entries(p.provenance ?? {}).filter(([, v]) => v === 'missing').length : 0
  return (
    <Card title={S.profile} actions={actions}>
      <p className={styles.confirmed}>
        <Icon name="clock" size={16} /> {p.confirmed_at ? S.lastConfirmed(formatDate(p.confirmed_at), p.days_since_confirmed ?? 0) : S.neverConfirmed}
      </p>
      {groups.length > 0 && (
        <ul className={styles.groupBadges} aria-label={S.checked}>
          {groups.map(([name, g]) => (
            <li key={name}>
              <Badge tone={g.verified ? 'low' : 'wait'} icon={g.verified ? 'check' : 'clock'}>
                {S.groups[name as keyof typeof S.groups]}: {g.verified ? S.verified : S.unverified}
              </Badge>
              {staff && p.checks?.[name] && <span className={styles.checkedBy}>{S.checkedBy(p.checks[name].by, formatDate(p.checks[name].at))}</span>}
            </li>
          ))}
        </ul>
      )}
      {staff && <p className="subtle small">{S.missing(missing)}</p>}
      <details className={styles.more}>
        <summary>{S.seeProfile}</summary>
        <DetailList items={rows} />
      </details>
    </Card>
  )
}

const blank = (v: string | number | null | undefined) => (v === null || v === undefined ? S.notGiven : String(v))

function Account({ account: a }: { account: AccountOut }) {
  return (
    <li className={styles.account}>
      <div className={styles.accountHead}>
        <span className={styles.accountName}>{S.accounts[a.kind]}</span>
        <strong className={styles.balance}>{formatKes(a.balance_kes)}</strong>
      </div>
      <p className="subtle small">{S.accountNote[a.kind]}</p>
      {a.entries.length > 0 ? (
        <details className={styles.more}>
          <summary>{S.lastEntries(a.entries.length)}</summary>
          <ul className={styles.entries}>
            {a.entries.map((e) => (
              <li key={e.id}>
                <span className={styles.entryWhat}>{S.entry[e.entry_type as EntryType]}<span className={styles.entryRef}>{e.reference}</span></span>
                <span className={styles.entryRight}>
                  <span className={e.amount_kes < 0 ? styles.out : styles.in}>{e.amount_kes < 0 ? '−' : '+'}{formatKes(Math.abs(e.amount_kes))}</span>
                  <span className={styles.entryDate}>{formatDate(e.posted_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : <p className="subtle small">{S.noEntries}</p>}
    </li>
  )
}

function Guarantors({ view, staff, onView }: { view: SaccoView; staff: boolean; onView?: (view: SaccoView) => void }) {
  const g = view.guarantee
  return (
    <Card title={S.guarantors} delay={0.06}>
      <DetailList items={[
        [S.capacity, <strong key="c">{formatKes(g.capacity_kes)}</strong>],
        [S.deposits, formatKes(g.deposits_kes)],
        [S.guaranteedNow, formatKes(g.guaranteed_kes)],
        ...(g.committed_kes > 0 ? [[S.committed, formatKes(g.committed_kes)] as [string, string]] : []),
      ]} />
      <h3 className={styles.subTitle}>{S.myGuarantors}</h3>
      {view.my_guarantors.length === 0 ? <p className="subtle small">{S.noGuarantors}</p> : (
        <ul className={styles.people}>{view.my_guarantors.map((p) => <Person key={p.id} p={p} staff={staff} side="mine" />)}</ul>
      )}
      <h3 className={styles.subTitle}>{S.iGuarantee}</h3>
      {view.i_guarantee.length === 0 ? <p className="subtle small">{S.noneGuaranteed}</p> : (
        <ul className={styles.people}>{view.i_guarantee.map((p) => <Person key={p.id} p={p} staff={staff} side="theirs" onView={onView} />)}</ul>
      )}
    </Card>
  )
}

function Person({ p, staff, side, onView }: {
  p: PledgeOut; staff: boolean; side: 'mine' | 'theirs'; onView?: (view: SaccoView) => void
}) {
  return (
    <li className={styles.person}>
      <span>{p.full_name}<span className={styles.entryRef}>{p.member_no}</span></span>
      {side === 'mine'
        ? (staff && p.capacity_kes !== null && p.capacity_kes !== undefined
            ? <Badge tone={p.has_capacity ? 'low' : 'wait'}>{S.capacityOf(p.capacity_kes)}</Badge>
            : <Badge tone={p.has_capacity ? 'low' : 'wait'}>{p.has_capacity ? S.hasCapacity : S.noCapacity}</Badge>)
        : <span className={styles.entryDate}>{p.guaranteed_kes ? S.guaranteedAmount(p.guaranteed_kes) : S.nothingYet}</span>}
      {side === 'theirs' && <Ceiling p={p} onView={staff ? undefined : onView} />}
    </li>
  )
}

/** What a guarantor agrees to stand behind this borrower for. Only they can change it. */
function Ceiling({ p, onView }: { p: PledgeOut; onView?: (view: SaccoView) => void }) {
  const toast = useToast()
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const set = p.max_amount_kes ?? null

  async function save(e: FormEvent) {
    e.preventDefault()
    const amount = Number(draft)
    if (!Number.isInteger(amount) || amount < 1) {
      setError(S.ceilingInvalid)
      return
    }
    try {
      onView?.(await api.setPledgeCeiling(p.id, amount))
      setDraft(null)
      setError(null)
      toast(S.ceilingSaved)
    } catch (err) {
      setError((err as ApiError).message)
    }
  }

  if (draft !== null) {
    return (
      <form className={styles.ceilingForm} onSubmit={save} noValidate>
        <Field id={`ceiling-${p.id}`} label={S.ceilingLabel(p.full_name)} error={error ?? undefined}>
          {(a) => <input {...a} className="input" inputMode="numeric" value={draft} onChange={(e) => setDraft(e.target.value)} />}
        </Field>
        <div className={styles.ceilingActions}>
          <button type="submit" className="btn btn-secondary btn-sm">{S.saveCeiling}</button>
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => { setDraft(null); setError(null) }}>{S.cancelCeiling}</button>
        </div>
      </form>
    )
  }
  return (
    <span className={styles.ceiling}>
      <span className="small subtle">{set === null ? S.noCeiling : S.ceiling(set)}</span>
      {onView && (
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => setDraft(set === null ? '' : String(set))}>
          {set === null ? S.setCeiling : S.changeCeiling}
        </button>
      )}
    </span>
  )
}

function LoanHistory({ loans }: { loans: LoanOut[] }) {
  return (
    <Card title={S.loans} delay={0.09}>
      {loans.length === 0 ? <EmptyState icon="file" title={S.noLoans} /> : (
        <ul className={styles.loans}>
          {loans.map((x) => (
            <li key={x.id} className={styles.loan}>
              <div className={styles.accountHead}>
                <strong>{formatKes(x.principal_kes)}</strong>
                <Badge tone={x.status === 'repaid' ? 'low' : x.status === 'defaulted' ? 'high' : x.status === 'reversed' ? 'neutral' : x.days_in_arrears > 0 ? 'wait' : 'info'}>
                  {S.loanStatus[x.status]}
                </Badge>
              </div>
              <p className="subtle small">{S.loanLine(formatDay(x.disbursed_on), x.term_months, x.monthly_instalment_kes)}</p>
              <p className="small">{S.paid(x.paid_kes)}{x.days_in_arrears > 0 && <> · <span className={styles.out}>{S.arrears(x.days_in_arrears)}</span></>}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
