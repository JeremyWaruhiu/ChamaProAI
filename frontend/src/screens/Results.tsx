import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, api } from '../api/client'
import type { Results as ResultsData } from '../api/types'
import {
  Caption, ConfusionMatrix, GroupedBars, HBars, Notes, Stat, Value,
} from '../components/Charts'
import { ErrorNotice } from '../components/Notice'
import { Badge, PageHeader, SkeletonPage } from '../components/ui'
import { formatDateTime } from '../lib/format'
import { NOT_MEASURED, fmt, isMeasured, pct } from '../lib/measure'
import { RISK_ORDER } from '../lib/risk'
import { t } from '../strings'
import styles from './Results.module.css'

const REPO = 'https://github.com/JeremyWaruhiu/ChamaProAI'
const CI_URL = `${REPO}/actions/workflows/ci.yml`
const ASR_LABEL: Record<string, string> = { paza: 'Paza', whisper_small: 'whisper-small' }
const ASR_COLOR: Record<string, string> = { paza: 'var(--green-600)', whisper_small: 'var(--wait)' }
const TONE = { Low: 'low', Medium: 'medium', High: 'high' } as const
const T = t.results

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={`card ${styles.card}`} aria-label={title}>
      <h3 className={styles.cardTitle}>{title}</h3>
      {children}
    </section>
  )
}

export function Results() {
  const [data, setData] = useState<ResultsData | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(async () => {
    try {
      setData(await api.results())
      setError(null)
    } catch (e) {
      setError(e as ApiError)
    }
  }, [])

  // oxlint-disable-next-line react/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { load() }, [load])

  return (
    <>
      <PageHeader title={T.title} badges={<Badge icon="lock">{T.readOnly}</Badge>}
                  lead={data && <>{T.exported(formatDateTime(data.generated_at))}<code>{data.generator ?? 'scripts/export_results.py'}</code>{T.liveNote}</>} />
      {error && <ErrorNotice doing={T.loadFailed} error={error} onRetry={load} />}
      {!data && !error && <SkeletonPage what={T.title} />}
      {data && <ResultsBody data={data} />}
    </>
  )
}

export function ResultsBody({ data }: { data: ResultsData }) {
  const { model_card: card, held_out: ho, class_balance: cb, random_forest: rf, shap, asr, live } = data
  const labels = ho?.labels ?? RISK_ORDER
  return (
    <div className={styles.grid}>
      <Card title={T.modelCard}>
        <dl className={styles.dl}>
          <dt>{T.estimator}</dt><dd>{card?.estimator ?? NOT_MEASURED}</dd>
          <dt>{T.protocol}</dt><dd>{card?.protocol ?? NOT_MEASURED}</dd>
          <dt>{T.seed}</dt><dd><Value v={card?.seed} digits={0} /></dd>
          <dt>{T.trainingRows}</dt><dd><Value v={card?.n_train} digits={0} /></dd>
          <dt>{T.features}</dt><dd><Value v={card?.n_features} digits={0} /></dd>
          <dt>{T.classes}</dt><dd>{card?.classes ? Object.values(card.classes).join(', ') : NOT_MEASURED}</dd>
          <dt>{T.trainedOn}</dt><dd>{card?.trained_on ?? NOT_MEASURED}</dd>
          <dt>{T.frame}</dt><dd>{card?.frame ?? NOT_MEASURED}</dd>
          <dt>{T.sha}</dt><dd className={styles.hash}>{card?.model_sha256 ?? NOT_MEASURED}</dd>
        </dl>
        <Notes notes={card?.notes} />
        <Caption source={card?.source} />
      </Card>

      <Card title={T.heldOut}>
        <div className={styles.stats}>
          <Stat label={T.auc}><Value v={ho?.auc_macro_ovr} /></Stat>
          <Stat label={T.f1Model}><Value v={ho?.macro_f1} /></Stat>
          <Stat label={T.f1Rule}><Value v={ho?.comparator_macro_f1} /></Stat>
          <Stat label={T.heldOutRows}><Value v={ho?.n_test} digits={0} /></Stat>
        </div>
        <HBars max={1} bars={[
          { label: T.barModel, value: ho?.macro_f1, tone: 'model' },
          { label: T.barRule, value: ho?.comparator_macro_f1, tone: 'baseline' },
        ]} />
        <Notes notes={ho?.notes} />
        <Caption source={[ho?.source, ho?.comparator_source].filter(Boolean).join('; comparator: ')}
                 validation={ho?.validation} />
      </Card>

      <Card title={T.confusion}>
        <ConfusionMatrix labels={labels} matrix={ho?.confusion_matrix} />
        <p className={`muted ${styles.small}`}>{T.confusionNote}</p>
        <Caption source={ho?.source} validation={ho?.validation} />
      </Card>

      <Card title={T.perClass}>
        <HBars max={1} bars={labels.map((l) => ({
          label: l, value: ho?.per_class?.[l]?.recall, tone: TONE[l as keyof typeof TONE] ?? 'model',
        }))} />
        <table className={styles.table}>
          <thead><tr><th>{T.cls}</th><th>{T.precision}</th><th>{T.recall}</th>{rf && <th>{T.recallRf}</th>}</tr></thead>
          <tbody>
            {labels.map((l) => (
              <tr key={l}>
                <td>{l}</td>
                <td><Value v={ho?.per_class?.[l]?.precision} /></td>
                <td><Value v={ho?.per_class?.[l]?.recall} /></td>
                {rf && <td><Value v={rf.per_class_recall?.[l]} /></td>}
              </tr>
            ))}
          </tbody>
        </table>
        <Notes notes={rf?.notes} />
        <Caption source={ho?.source} validation={ho?.validation} />
      </Card>

      <Card title={T.shap}>
        {shap?.top_features?.length
          ? <HBars bars={shap.top_features.map((f) => ({ label: f.feature, value: f.mean_abs_shap }))}
                   format={(v) => v.toFixed(4)} />
          : <p className={styles.na}>{T.shapNone} {NOT_MEASURED}</p>}
        <Notes notes={shap?.notes} />
        <Caption source={`${shap?.source ?? NOT_MEASURED}${isMeasured(shap?.sample_size) ? T.sample(shap.sample_size) : ''}`}
                 validation={shap?.validation} />
      </Card>

      <Card title={T.balance}>
        {(['train', 'test'] as const).map((split) => {
          const counts = cb?.[split]
          const total = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : 0
          return (
            <div key={split} className={styles.split}>
              <p className={styles.splitTitle}>{split === 'train' ? T.train : T.test}</p>
              <HBars max={1} format={(v) => pct(v)} bars={(cb?.labels ?? RISK_ORDER).map((l) => ({
                label: counts ? `${l} (${counts[l] ?? 0})` : l,
                value: counts && total ? (counts[l] ?? 0) / total : null,
                tone: TONE[l as keyof typeof TONE] ?? 'model',
              }))} />
            </div>
          )
        })}
        <Notes notes={cb?.notes} />
        <Caption source={cb?.source} validation={cb?.validation} />
      </Card>

      <Card title={T.asr}>
        <AsrSection asr={asr} />
      </Card>

      <Card title={T.live}>
        <div className={styles.stats}>
          <Stat label={T.liveInterviews}><Value v={live.interview_count} digits={0} /></Stat>
          <Stat label={T.assessments}><Value v={live.assessment_count} digits={0} /></Stat>
          <Stat label={T.completeness}><Value v={live.mean_extraction_completeness} percent /></Stat>
          <Stat label={T.agrees}>
            <Value v={live.decision_agreement.rate} percent />
          </Stat>
        </div>
        <HBars bars={Object.entries(live.risk_class_distribution).map(([k, v]) => ({
          label: k, value: v, tone: TONE[k as keyof typeof TONE] ?? 'model',
        }))} format={(v) => String(v)} />
        <p className={`muted ${styles.small}`}>
          {T.agreement(live.decision_agreement.agreements, live.decision_agreement.decisions, live.decision_agreement.rule)}
          {T.practiceLeftOut(live.practice_interview_count)}
        </p>
        <Caption source={T.liveSource(live.source)} validation={T.liveValidation} />
      </Card>

      <Card title={T.ci}>
        <p>
          <a href={CI_URL} target="_blank" rel="noreferrer">
            <img src={`${CI_URL}/badge.svg`} alt={T.ciBadge} height={20} />
          </a>
        </p>
        <p className={styles.small}>
          {T.ciBody} <a href={CI_URL} target="_blank" rel="noreferrer">{T.viewRuns}</a>.
        </p>
        <Caption source=".github/workflows/ci.yml" validation={T.ciValidation} />
      </Card>
    </div>
  )
}

function AsrSection({ asr }: { asr: ResultsData['asr'] }) {
  if (!asr) return <p className={styles.na}>{T.asrNone} {NOT_MEASURED}</p>
  const systems = Object.keys(asr.systems)
  const name = (s: string) => ASR_LABEL[s] ?? s
  const domains = asr.domains.length ? asr.domains
    : [...new Set(systems.flatMap((s) => Object.keys(asr.systems[s].by_domain ?? {})))]
  return (
    <>
      <table className={styles.table}>
        <thead>
          <tr><th>{T.system}</th><th>{T.clips}</th><th>{T.collapses}</th><th>{T.yield}</th><th>chrF++</th><th>BLEU</th></tr>
        </thead>
        <tbody>
          {systems.map((s) => {
            const o = asr.systems[s].overall
            return (
              <tr key={s}>
                <td>{name(s)}</td>
                <td><Value v={o?.n} digits={0} /></td>
                <td><Value v={o?.collapse_count} digits={0} /></td>
                <td><Value v={o?.yield} percent /></td>
                <td><Value v={o?.chrf_pp} digits={2} /></td>
                <td><Value v={o?.bleu} digits={2} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className={styles.splitTitle}>{T.byDomain}</p>
      <GroupedBars categories={domains} series={systems.map((s) => ({
        name: name(s), color: ASR_COLOR[s] ?? 'var(--ink-3)',
        values: domains.map((d) => asr.systems[s].by_domain?.[d]?.chrf_pp),
      }))} />
      <details className={styles.small}>
        <summary>{T.perDomain}</summary>
        <table className={styles.table}>
          <thead>
            <tr><th>{T.domain}</th>{systems.map((s) => <th key={s}>{T.domainCols(name(s))}</th>)}</tr>
          </thead>
          <tbody>
            {domains.map((d) => (
              <tr key={d}>
                <td>{d.replace(/_/g, ' ')}</td>
                {systems.map((s) => {
                  const b = asr.systems[s].by_domain?.[d]
                  return <td key={s}>{fmt(b?.chrf_pp, 2)} / {fmt(b?.bleu, 2)} / {pct(b?.yield, 0)} / {fmt(b?.collapse_count, 0)}</td>
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
      <Notes notes={asr.notes} />
      <Caption source={asr.source}
               validation={`${asr.validation ?? ''}${asr.collapse_rule ? `; collapse = ${asr.collapse_rule}` : ''}`} />
    </>
  )
}
