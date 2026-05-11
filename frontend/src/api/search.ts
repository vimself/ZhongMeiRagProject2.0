import { apiClient } from '@/api/client'

export interface SearchHit {
  id: string
  index: number
  chunk_id: string | null
  document_id: string
  document_title: string
  knowledge_base_id: string
  section_path: string[]
  section_text: string
  page_start: number | null
  page_end: number | null
  bbox: { x?: number; y?: number; width?: number; height?: number } | null
  snippet: string
  score: number
  preview_url: string
  download_url: string
}

export interface SearchResponse {
  items: SearchHit[]
  total: number
  page: number
  page_size: number
}

export interface SearchParams {
  query: string
  kb_id?: string
  doc_kind?: string
  scheme_type?: string
  content_type?: string
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
  sort_by?: string
}

export interface HotKeyword {
  keyword: string
  count: number
}

export interface HotKeywordsResponse {
  items: HotKeyword[]
}

export interface DocTypeCount {
  doc_kind: string
  count: number
}

export interface SchemeTypeCount {
  scheme_type: string
  count: number
}

export interface DocTypesResponse {
  doc_kinds: DocTypeCount[]
  scheme_types: SchemeTypeCount[]
}

export interface ExportJobOut {
  job_id: string
  status: string
  created_at: string
}

export interface ExportJobStatus {
  job_id: string
  status: string
  result_count: number
  file_size: number | null
  download_url: string | null
  error: string | null
  created_at: string
}

export function searchDocuments(params: SearchParams) {
  return apiClient.post<SearchResponse>('/search/documents', params)
}

export function fetchHotKeywords(limit?: number) {
  return apiClient.get<HotKeywordsResponse>('/search/hot-keywords', { params: { limit } })
}

export function fetchDocTypes() {
  return apiClient.get<DocTypesResponse>('/search/doc-types')
}

export function createExportJob(
  params: Omit<SearchParams, 'page' | 'page_size' | 'sort_by'> & { format?: string },
) {
  return apiClient.post<ExportJobOut>('/search/export', params)
}

export function getExportJobStatus(jobId: string) {
  return apiClient.get<ExportJobStatus>(`/search/export/${jobId}`)
}

export function downloadExportUrl(jobId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v2'
  return `${base}/search/export/${jobId}/download`
}
