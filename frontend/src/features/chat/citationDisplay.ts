import type { ChatCitation } from '@/api/chat'

export interface DocumentReferenceSummary {
  key: string
  label: string
  clauses: string[]
  citations: ChatCitation[]
}

function sourceLabel(citation: ChatCitation): string {
  const title = citation.document_title || citation.document_id || '未命名文档'
  return title.split(/[\\/]/).filter(Boolean).pop() || title
}

function compareClause(a: string, b: string): number {
  const left = a.split('.').map(Number)
  const right = b.split('.').map(Number)
  const length = Math.max(left.length, right.length)
  for (let i = 0; i < length; i += 1) {
    const diff = (left[i] ?? 0) - (right[i] ?? 0)
    if (diff !== 0) return diff
  }
  return a.localeCompare(b, 'zh-Hans-CN')
}

function extractLastClause(text: string): string | null {
  const matches = [...text.matchAll(/(?:第\s*)?(\d+(?:\.\d+){1,4})\s*(?:条)?/g)]
  return matches.length > 0 ? (matches[matches.length - 1]?.[1] ?? null) : null
}

export function citationClause(citation: ChatCitation): string | null {
  for (const section of [...(citation.section_path ?? [])].reverse()) {
    const clause = extractLastClause(section)
    if (clause) return clause
  }
  return extractLastClause(citation.snippet || '') ?? extractLastClause(citation.section_text || '')
}

function finiteScore(citation: ChatCitation): number {
  return Number.isFinite(citation.score) ? citation.score : Number.NEGATIVE_INFINITY
}

function sourceTieBreaker(a: ChatCitation, b: ChatCitation): number {
  const titleDiff = sourceLabel(a).localeCompare(sourceLabel(b), 'zh-Hans-CN')
  if (titleDiff !== 0) return titleDiff
  return String(a.id).localeCompare(String(b.id), 'zh-Hans-CN')
}

export function compareCitationsByRelevance(a: ChatCitation, b: ChatCitation): number {
  const scoreDiff = finiteScore(b) - finiteScore(a)
  if (scoreDiff !== 0) return scoreDiff
  const indexDiff = (a.index ?? 0) - (b.index ?? 0)
  if (indexDiff !== 0) return indexDiff
  return sourceTieBreaker(a, b)
}

function sortCitationsInDocument(citations: ChatCitation[]): ChatCitation[] {
  return [...citations].sort((a, b) => {
    const left = citationClause(a)
    const right = citationClause(b)
    if (left && right) {
      const diff = compareClause(left, right)
      if (diff !== 0) return diff
    }
    if (left && !right) return -1
    if (!left && right) return 1
    return a.index - b.index
  })
}

export function documentReferenceSummaries(citations: ChatCitation[]): DocumentReferenceSummary[] {
  const groups = new Map<string, DocumentReferenceSummary>()
  for (const citation of orderedCitations(citations)) {
    const key = citation.document_id || citation.document_title || citation.id
    const existing = groups.get(key)
    if (existing) {
      existing.citations.push(citation)
    } else {
      groups.set(key, {
        key,
        label: sourceLabel(citation),
        clauses: [],
        citations: [citation],
      })
    }
  }

  return [...groups.values()].map((group) => {
    const sortedCitations = sortCitationsInDocument(group.citations)
    const clauses = [...new Set(sortedCitations.map(citationClause).filter(Boolean) as string[])]
    clauses.sort(compareClause)
    return {
      ...group,
      clauses,
      citations: sortedCitations,
    }
  })
}

export function orderedCitations(citations: ChatCitation[]): ChatCitation[] {
  return [...citations].sort(compareCitationsByRelevance)
}

export function formatDocumentReference(summary: DocumentReferenceSummary): string {
  if (summary.clauses.length === 0) {
    return `${summary.label}。`
  }
  return `${summary.label}：第${summary.clauses.join('条、')}条。`
}

export function formatCitationReference(citation: ChatCitation): string {
  const label = sourceLabel(citation)
  const page =
    citation.page_start == null
      ? ''
      : citation.page_end == null || citation.page_end === citation.page_start
        ? `p.${citation.page_start}`
        : `p.${citation.page_start}-${citation.page_end}`
  const clause = citationClause(citation)
  const section = citation.section_path?.length
    ? citation.section_path[citation.section_path.length - 1]
    : ''
  const location = clause ? `第${clause}条` : section || ''
  const parts = [location, page].filter(Boolean)
  return parts.length > 0 ? `${label}：${parts.join('，')}。` : `${label}。`
}
