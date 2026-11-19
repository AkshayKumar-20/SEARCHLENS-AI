import { useState } from 'react'
import { runAudit } from './lib/api'
import type { ActionPlan, AuditResult, BrokenLink, Metric, MetricStatus, TitleMetaRow } from './types'

const STATUS_STYLE: Record<MetricStatus, string> = {
  good: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  bad: 'bg-rose-50 text-rose-700',
  unavailable: 'bg-slate-100 text-slate-500',
  not_applicable: 'bg-slate-100 text-slate-500',
}
const STATUS_LABEL: Record<MetricStatus, string> = {
  good: 'Pass', warning: 'Warning', bad: 'Fail', unavailable: 'Not measured', not_applicable: 'N/A',
}

export function App() {
  const [url, setUrl] = useState('')
  const [maxPages, setMaxPages] = useState(10)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AuditResult | null>(null)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setResult(null)
    try {
      setResult(await runAudit(url.trim(), maxPages))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The audit failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10">
      <h1 className="text-3xl font-black tracking-tight">SearchLens AI</h1>
      <p className="mt-1 text-slate-500">Crawl a product website and report its top 5 SEO metrics.</p>

      <form onSubmit={submit} className="card mt-6 flex flex-col gap-3 p-5 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm font-semibold">
          Website URL
          <input required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://www.example.com"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" />
        </label>
        <label className="text-sm font-semibold">
          Max pages
          <input type="number" min={1} max={50} value={maxPages} onChange={e => setMaxPages(Number(e.target.value))}
            className="mt-1 w-24 rounded-lg border border-slate-300 px-3 py-2 font-normal" />
        </label>
        <button disabled={busy} className="rounded-lg bg-blue-600 px-5 py-2 font-semibold text-white disabled:opacity-50">
          {busy ? 'Crawling…' : 'Run audit'}
        </button>
      </form>
      {busy && <p className="mt-3 text-sm text-slate-500">Crawling pages and checking every internal link. This can take a minute.</p>}
      {error && <p className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {result && <Report result={result} />}
    </main>
  )
}

function Report({ result }: { result: AuditResult }) {
  const titleMeta = result.metrics.find(m => m.id === 'title_meta')
  return (
    <div className="mt-8 space-y-8">
      <section className="card flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="break-all font-semibold">{result.url}</p>
          <p className="mt-1 text-sm text-slate-500">{result.pages_crawled} page(s) crawled · {result.summary}</p>
          <p className="mt-1 text-xs text-slate-400">
            Score uses {Math.round(result.coverage * 100)}% of the metric weight; metrics that were not measured or do not apply are left out.
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Overall SEO score</p>
          <p className="text-5xl font-black">{result.overall_score}<span className="text-xl text-slate-400">/100</span></p>
        </div>
      </section>

      <ActionList plan={result.action_plan} />

      <section>
        <h2 className="text-xl font-bold">The five metrics</h2>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          {result.metrics.map(metric => <MetricCard key={metric.id} metric={metric} />)}
        </div>
      </section>

      {titleMeta?.pages && <TitleMetaTable rows={titleMeta.pages} />}
      <BrokenLinksTable links={result.broken_links} />
      {result.discovery_gaps.length > 0 && (
        <section className="card p-5">
          <h2 className="font-bold">Crawl notes</h2>
          <ul className="mt-2 list-disc pl-5 text-sm text-slate-600">{result.discovery_gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul>
        </section>
      )}
    </div>
  )
}

function ActionList({ plan }: { plan: ActionPlan }) {
  const label = plan.source === 'llm'
    ? `Written by ${plan.model} from the crawl findings. Scores above are not from the LLM.`
    : plan.source === 'fallback'
      ? `Rule-based fallback (no LLM output used): ${plan.reason}`
      : plan.reason
  return (
    <section className="card p-6">
      <h2 className="text-xl font-bold">What to do this week</h2>
      <p className="mt-1 text-xs text-slate-500">{label}</p>
      <ol className="mt-4 space-y-3">
        {plan.actions.map(action => (
          <li key={action.priority} className="flex gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white">{action.priority}</span>
            <div>
              <p className="font-semibold">{action.action}</p>
              {action.why && <p className="text-sm text-slate-500">{action.why}</p>}
              {action.pages.length > 0 && <p className="mt-1 break-all text-xs text-slate-400">{action.pages.join(' · ')}</p>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function MetricCard({ metric }: { metric: Metric }) {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold">{metric.title}</p>
          <p className="text-xs text-slate-400">{metric.mandatory ? 'Mandatory' : 'Chosen'} · weight {metric.weight}</p>
        </div>
        <div className="text-right">
          <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${STATUS_STYLE[metric.status]}`}>{STATUS_LABEL[metric.status]}</span>
          <p className="mt-1 text-2xl font-black">{metric.score ?? '—'}</p>
        </div>
      </div>
      <p className="mt-3 text-sm">{metric.summary}</p>
      <p className="mt-2 text-xs text-slate-500"><b>Pass:</b> {metric.target}</p>
      {metric.evidence.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-slate-500">
          {metric.evidence.slice(0, 5).map((item, i) => <li key={i} className="break-all rounded bg-slate-50 px-2 py-1">{item}</li>)}
        </ul>
      )}
    </div>
  )
}

function TitleMetaTable({ rows }: { rows: TitleMetaRow[] }) {
  return (
    <section className="card overflow-x-auto p-5">
      <h2 className="font-bold">Title &amp; meta description by page</h2>
      <table className="mt-3 w-full text-left text-sm">
        <thead className="text-xs uppercase text-slate-400">
          <tr><th className="py-2 pr-3">Page</th><th className="pr-3">Title (30–60)</th><th className="pr-3">Description (70–160)</th><th>Result</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map(row => (
            <tr key={row.url} className="align-top">
              <td className="max-w-xs break-all py-2 pr-3">{row.url}</td>
              <td className="pr-3">{row.title_present ? `${row.title_length} chars` : 'Missing'}</td>
              <td className="pr-3">{row.meta_description_present ? `${row.meta_description_length} chars` : 'Missing'}</td>
              <td className={row.status === 'good' ? 'text-emerald-700' : 'text-rose-700'}>{row.status === 'good' ? 'Pass' : row.issues.join('; ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function BrokenLinksTable({ links }: { links: BrokenLink[] }) {
  return (
    <section className="card overflow-x-auto p-5">
      <h2 className="font-bold">Broken internal links</h2>
      {links.length === 0 ? <p className="mt-2 text-sm text-emerald-700">None found.</p> : (
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-xs uppercase text-slate-400"><tr><th className="py-2 pr-3">Found on</th><th className="pr-3">Broken link</th><th>HTTP</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {links.map((link, i) => (
              <tr key={i}><td className="break-all py-2 pr-3">{link.source}</td><td className="break-all pr-3">{link.destination}</td><td>{link.status}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
