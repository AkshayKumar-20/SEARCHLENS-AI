import type { AuditResult } from '../types'

export async function runAudit(url: string, maxPages: number): Promise<AuditResult> {
  const response = await fetch('/api/audit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, max_pages: maxPages }),
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    // The backend always sends a readable string in "detail" for 400/422 errors.
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (HTTP ${response.status})`)
  }
  return body as AuditResult
}
