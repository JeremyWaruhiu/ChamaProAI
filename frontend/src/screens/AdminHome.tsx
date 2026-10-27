import { useCallback } from 'react'
import { api } from '../api/client'
import type { AsrStatus, AuditEntry, Health, Outcome } from '../api/types'
import { Icon } from '../components/Icon'
import { ErrorNotice } from '../components/Notice'
import { Badge, Card, DetailList, EmptyState, Kpi, PageHeader, SkeletonList } from '../components/ui'
import { cx } from '../lib/cx'
import { useLoad } from '../hooks/useLoad'
import { formatDateTime } from '../lib/format'
import { isMeasured, pct } from '../lib/measure'
import { RISK_ORDER } from '../lib/risk'
import { paths } from '../lib/router'
import { outcomeLabel } from '../lib/status'
import { t } from '../strings'
import styles from './AdminHome.module.css'

const H = t.adminHome
const OUTCOMES: Outcome[] = ['approve', 'approve_with_guarantor', 'approve_reduced', 'refer', 'decline']

export function AdminHome() {
  const results = useLoad(useCallback(() => api.results(), []))
  const apps = useLoad(useCallback(() => api.applications({ limit: 500 }), []))
  const audit = useLoad(useCallback(() => api.audit({ limit: 8 }), []))
  const health = useLoad(useCallback(() => api.health(), []))

  const live = results.data?.live
  const liveApps = apps.data?.filter((a) => a.mode !== 'practice') ?? null
  const outcomes = liveApps ? OUTCOMES.map((o) => ({ key: o, label: outcomeLabel(o), value: liveApps.filter((a) => a.outcome === o).length })) : null
  const decided = outcomes?.reduce((n, o) => n + o.value, 0) ?? 0
  const dist = live ? RISK_ORDER.map((c) => ({ key: c, label: t.risk.badge(c), value: live.risk_class_distribution[c] ?? 0 })) : null
  const assessed = dist?.reduce((n, d) => n + d.value, 0) ?? 0
  const da = live?.decision_agreement
  const ra = live?.rule_agreement

  return (
    <>
      <PageHeader title={H.title} lead={H.lead}
                  actions={<a href={paths.results()} className="btn btn-secondary"><Icon name="chart" /> {t.nav.results}</a>} />

      {results.error && <ErrorNotice doing={H.statsFailed} error={results.error} onRetry={results.reload} />}

      <div className={styles.kpis}>
        <Kpi icon="mic" tone="wait" label={H.interviews} value={live ? live.interview_count : '–'} />
        <Kpi icon="scale" tone="info" label={H.assessments} value={live ? live.assessment_count : '–'} />
        <Kpi icon="file" tone="attention" label={H.applications} value={liveApps ? liveApps.length : '–'} href={paths.applications()} />
        <Kpi icon="users" tone="low" label={H.agreement}
             value={da ? (isMeasured(da.rate) ? pct(da.rate, 0) : '–') : '–'}
             note={da ? (isMeasured(da.rate) ? H.agreementOf(da.agreements, da.decisions) : H.notMeasured) : undefined} />
      </div>

      <div className={styles.grid}>
        <Card title={H.distribution}>
          {!dist ? <SkeletonList rows={3} what={H.distribution} />
            : assessed === 0 ? <EmptyState icon="chart" title={H.distributionEmpty} />
              : <Bars items={dist} tone={(k) => k.toLowerCase()} total={assessed} />}
        </Card>

        <Card title={H.outcomes} delay={0.05}>
          <p className="subtle small">{H.outcomesNote}</p>
          {apps.error && <ErrorNotice doing={t.applications.loadFailed} error={apps.error} onRetry={apps.reload} />}
          {!outcomes ? <SkeletonList rows={3} what={H.outcomes} />
            : decided === 0 ? <EmptyState icon="file" title={H.outcomesEmpty} />
              : <Bars items={outcomes} tone={() => 'model'} total={decided} />}
        </Card>

        <Card title={H.agreementTitle} delay={0.1}>
          <div className={styles.rings}>
            <Ring label={H.agreement} rate={da?.rate ?? null} note={da && isMeasured(da.rate) ? H.agreementOf(da.agreements, da.decisions) : H.notMeasured} />
            <Ring label={H.ruleAgreement} rate={ra?.rate ?? null} note={ra && isMeasured(ra.rate) ? H.ruleOf(ra.agreements, ra.agreements + ra.divergences) : H.notMeasured} />
          </div>
          {da && <p className="subtle small">{da.rule}</p>}
        </Card>

        <Card title={H.speech} delay={0.15}>
          {health.error && <ErrorNotice doing={H.healthFailed} error={health.error} onRetry={health.reload} />}
          {!health.data && !health.error && <SkeletonList rows={3} what={H.speech} />}
          {health.data && <Speech h={health.data} />}
        </Card>
      </div>

      <Card title={H.activity} delay={0.2}
            actions={<a href={paths.audit()} className="btn btn-quiet btn-sm">{H.viewAudit}</a>}>
        {audit.error && <ErrorNotice doing={t.audit.loadFailed} error={audit.error} onRetry={audit.reload} />}
        {!audit.data && !audit.error && <SkeletonList rows={4} what={H.activity} />}
        {audit.data?.length === 0 && <EmptyState icon="scroll" title={H.activityEmpty} />}
        {audit.data && audit.data.length > 0 && <Activity entries={audit.data} />}
      </Card>
    </>
  )
}

/** Horizontal bars, each labelled with its name and count (never colour alone). */
function Bars({ items, tone, total }: { items: { key: string; label: string; value: number }[]; tone: (key: string) => string; total: number }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className={styles.bars}>
      {items.map((i) => (
        <li key={i.key} title={`${i.label}: ${i.value} (${pct(total ? i.value / total : 0, 0)})`}>
          <span className={styles.barLabel}>{i.label}</span>
          <span className={styles.barTrack}>
            {i.value > 0 && <span className={cx(styles.barFill, styles[tone(i.key)])} style={{ width: `${(100 * i.value) / max}%` }} />}
          </span>
          <span className={`${styles.barValue} num`}>{i.value}</span>
        </li>
      ))}
    </ul>
  )
}

function Ring({ label, rate, note }: { label: string; rate: number | null; note: string }) {
  const r = 34
  const c = 2 * Math.PI * r
  const measured = isMeasured(rate)
  return (
    <figure className={styles.ring}>
      <svg viewBox="0 0 80 80" width="96" height="96" role="img" aria-label={`${label}: ${measured ? pct(rate, 0) : H.notMeasured}`}>
        <circle cx="40" cy="40" r={r} fill="none" stroke="var(--surface-sunken)" strokeWidth="8" />
        {measured && (
          <circle cx="40" cy="40" r={r} fill="none" stroke="var(--green-600)" strokeWidth="8" strokeLinecap="round"
                  strokeDasharray={`${c * rate} ${c}`} transform="rotate(-90 40 40)" />
        )}
        <text x="40" y="45" textAnchor="middle" className={styles.ringValue}>{measured ? pct(rate, 0) : '–'}</text>
      </svg>
      <figcaption>
        <strong>{label}</strong>
        <span className="subtle small">{note}</span>
      </figcaption>
    </figure>
  )
}

function Speech({ h }: { h: Health }) {
  const row = (lang: string, a: AsrStatus | undefined) => (
    <div className={styles.engine} key={lang}>
      <p className={styles.engineTitle}><Icon name="cpu" size={18} /> {H.speechFor(lang)}</p>
      {a?.loaded ? (
        <DetailList items={[
          [H.engine, <Badge key="e" tone="info">{a.engine ?? '—'}</Badge>],
          [H.device, <Badge key="d" tone={a.device === 'GPU' ? 'low' : 'neutral'}>{a.device ?? '—'}</Badge>],
          [H.model, <span key="m" className={styles.mono}>{a.model ?? '—'}</span>],
        ]} />
      ) : <p className="subtle small">{a?.error ?? (lang === t.common.english ? H.loadsOnFirstUse : H.notLoaded)}</p>}
    </div>
  )
  return (
    <div className={styles.speech}>
      <Badge tone={h.status === 'ok' ? 'low' : 'medium'} icon={h.status === 'ok' ? 'check' : 'alert'}>{H.healthStatus[h.status]}</Badge>
      {row(t.common.kikuyu, h.asr.kik)}
      {row(t.common.english, h.asr.en)}
      <DetailList items={[
        [H.decoding, h.asr_decoding],
        [H.classifier, h.classifier_present === false ? H.missing : H.present],
        ...(h.extraction_model ? [[H.extraction, h.extraction_model] as [string, string]] : []),
      ]} />
    </div>
  )
}

function Activity({ entries }: { entries: AuditEntry[] }) {
  return (
    <ul className={styles.activity}>
      {entries.map((e) => (
        <li key={e.id} className={styles.activityItem}>
          <span className={styles.activityDot} aria-hidden />
          <div>
            <p><strong>{e.actor ?? t.audit.script}</strong> · <code>{e.action}</code> · {t.audit.entities[e.entity] ?? e.entity}{e.entity_id ? ` ${e.entity_id}` : ''}</p>
            <p className="subtle small">{formatDateTime(e.created_at)}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
