// Mirror of backend/app/schemas.py. The frontend only displays these values;
// it never computes a score.

export type MetricStatus = 'good' | 'warning' | 'bad' | 'unavailable' | 'not_applicable'

export interface TitleMetaRow {
  url: string
  title: string
  title_present: boolean
  title_length: number
  meta_description: string
  meta_description_present: boolean
  meta_description_length: number
  status: 'good' | 'bad'
  issues: string[]
}

export interface BrokenLink { source: string; destination: string; status: number; anchor_text?: string }

export interface Metric {
  id: string
  title: string
  mandatory: boolean
  weight: number
  status: MetricStatus
  score: number | null
  summary: string
  target: string
  bad: string
  action: string
  evidence: string[]
  pages?: TitleMetaRow[]
  broken_links?: BrokenLink[]
}

export interface ActionItem { priority: number; metric_id: string; action: string; why: string; pages: string[] }

export interface ActionPlan {
  source: 'llm' | 'fallback' | 'none'
  provider: string
  model: string | null
  reason: string
  actions: ActionItem[]
}

export interface AuditResult {
  id: string
  url: string
  created_at: string
  pages_crawled: number
  overall_score: number
  coverage: number
  summary: string
  metrics: Metric[]
  action_plan: ActionPlan
  broken_links: BrokenLink[]
  crawl_errors: { url: string; type: string; message: string; status?: number }[]
  discovery_gaps: string[]
}
