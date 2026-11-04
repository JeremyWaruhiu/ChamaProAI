import { useCallback, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { Member } from '../api/types'
import { ApplicationStatusBadge, OutcomeBadge, RiskBadge } from '../components/Badges'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { useToast } from '../components/toastContext'
import { Badge, Card, DetailList, EmptyState, Field, Modal, PageHeader, PracticeBadge, SkeletonPage } from '../components/ui'
import { useLoad } from '../hooks/useLoad'
import { formatDate, formatDateTime, formatDay, formatKes, parseShillings, todayYmd } from '../lib/format'
import { paths } from '../lib/router'
import { t } from '../strings'
import { SaccoPanels } from './MySacco'
import styles from './Tables.module.css'

const M = t.members
const V = t.verify

export function MemberDetail({ id }: { id: number }) {
  const load = useCallback(() => Promise.all([api.member(id), api.applications({ member_id: id }), api.memberSacco(id),
                                              api.applicantForm()]), [id])
  const { data, error, reload } = useLoad(load)
  const [verifying, setVerifying] = useState(false)
  const [verifyingProfile, setVerifyingProfile] = useState(false)
  const toast = useToast()
  if (error) return <ErrorNotice doing={M.detailFailed} error={error} onRetry={reload} />
  if (!data) return <SkeletonPage what={M.title} />
  const [member, apps, sacco, options] = data
  const onLedger = (sacco.accounts.find((a) => a.kind === 'deposits')?.entries.length ?? 0) > 0

  async function verifyProfile() {
    setVerifyingProfile(true)
    try {
      await api.verifyProfile(id)
      toast(t.sacco.profileVerified)
      await reload()
    } catch (e) {
      toast((e as ApiError).message, 'error')
    } finally {
      setVerifyingProfile(false)
    }
  }

  return (
    <>
      <PageHeader eyebrow={<a href={paths.members()}>{M.title}</a>} title={member.full_name} lead={member.member_no}
                  actions={<a href={paths.start(member.id)} className="btn btn-accent"><Icon name="mic" /> {M.startInterview}</a>} />
      <div className={styles.detailGrid}>
        <Card title={M.details}>
          <DetailList items={[
            [M.memberNo, member.member_no],
            [M.phone, member.phone ?? '—'],
            [M.joined, formatDay(member.joined_on)],
            [M.login, member.user_id ? M.hasLogin : M.noLogin],
            ...(member.email ? [[V.email, member.email] as [string, string]] : []),
          ]} />
          {member.self_signed_up && <p className="subtle small">{V.selfSignup}</p>}
        </Card>
        <Card title={V.title} delay={0.03} actions={
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setVerifying(true)}><Icon name="edit" size={16} /> {V.action}</button>
        }>
          <DetailList items={[
            [V.savings, onLedger ? formatKes(sacco.guarantee.deposits_kes)
              : member.savings_kes === null || member.savings_kes === undefined ? '—' : formatKes(member.savings_kes)],
            [t.apply.savingsVerification, onLedger ? <Badge key="s" tone="low" icon="check">{t.savingsStatus.ledger}</Badge> : <SavingsBadge key="s" m={member} />],
          ]} />
          {!onLedger && member.savings_verified_by && member.savings_verified_at && (
            <p className="subtle small">{V.verifiedBy(member.savings_verified_by, formatDateTime(member.savings_verified_at))}</p>
          )}
        </Card>
        <Card title={M.applications} delay={0.05}>
          {apps.length === 0 ? <EmptyState icon="file" title={M.noApplications} /> : (
            <ul className={styles.cardList}>
              {apps.map((a) => (
                <li key={a.id}>
                  <a href={paths.application(a.id)} className={styles.cardLink}>
                    <span>
                      <strong>{t.applications.detailTitle(a.id)}</strong> · {formatKes(a.amount_requested_kes)}
                      <span className={styles.sub}>{formatDate(a.created_at)}{a.mode === 'practice' && <PracticeBadge />}</span>
                    </span>
                    <span className={styles.badges}>
                      {a.risk_class && <RiskBadge risk={a.risk_class} />}
                      {a.outcome ? <OutcomeBadge outcome={a.outcome} /> : <ApplicationStatusBadge status={a.status} />}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <div className={styles.saccoPanels}>
        <SaccoPanels view={sacco} options={options} staff actions={
          <button type="button" className="btn btn-primary btn-sm" disabled={verifyingProfile || !sacco.profile.confirmed_at} onClick={verifyProfile}>
            {verifyingProfile ? <span className="spinner" aria-hidden /> : <Icon name="check" size={16} />} {t.sacco.verifyProfile}
          </button>
        } />
      </div>
      {verifying && <VerifyModal member={member} onLedger={onLedger} onClose={() => setVerifying(false)} onSaved={reload} />}
    </>
  )
}

function SavingsBadge({ m }: { m: Member }) {
  const status = m.savings_kes === null || m.savings_kes === undefined ? 'none'
    : m.savings_verified_at ? 'verified' : 'self_declared'
  return <Badge tone={status === 'verified' ? 'low' : status === 'none' ? 'neutral' : 'wait'}>{t.savingsStatus[status]}</Badge>
}

function VerifyModal({ member, onLedger, onClose, onSaved }: { member: Member; onLedger: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const toast = useToast()
  const [amount, setAmount] = useState(member.savings_kes === null || member.savings_kes === undefined ? '' : String(member.savings_kes))
  const [joined, setJoined] = useState(member.joined_on)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const savings = parseShillings(amount)
  const dateOk = !!joined && joined <= todayYmd()

  async function save() {
    setTried(true)
    if ((!onLedger && savings === null) || !dateOk) return
    setBusy(true)
    setError(null)
    try {
      await api.verifyMember(member.id, onLedger ? { joined_on: joined } : { savings_kes: savings!, joined_on: joined })
      toast(V.saved)
      await onSaved()
      onClose()
    } catch (e) {
      setError(e as ApiError)
      setBusy(false)
    }
  }

  return (
    <Modal open title={V.modalTitle} onClose={onClose}
           actions={<>
             <button type="button" className="btn btn-quiet" onClick={onClose}>{t.common.cancel}</button>
             <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
               {busy && <span className="spinner" aria-hidden />} {V.save}
             </button>
           </>}>
      <p className="muted small">{V.modalLead}</p>
      {onLedger ? <p className="subtle small">{t.sacco.officerSavingsNote}</p> : (
        <Field id="ver-amount" label={V.amount} error={tried && savings === null ? V.amountError : null}>
          {(p) => <input {...p} className="input num" inputMode="numeric" autoComplete="off" value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
      )}
      <Field id="ver-joined" label={V.joined} error={tried && !dateOk ? V.joinedError : null}>
        {(p) => <input {...p} className="input" type="date" max={todayYmd()} value={joined} onChange={(e) => setJoined(e.target.value)} />}
      </Field>
      {error && <ErrorNotice doing={V.failed} error={error} />}
    </Modal>
  )
}
