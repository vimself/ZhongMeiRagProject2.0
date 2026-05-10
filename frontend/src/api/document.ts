import { apiClient } from '@/api/client'
import type {
  DocumentDetailResponse,
  DocumentListResponse,
  DocumentOut,
  DocumentUploadResponse,
  IngestJobProgress,
} from '@/api/types'

export function uploadDocument(
  kbId: string,
  payload: {
    file: File
    title?: string
    doc_kind?: string
    scheme_type?: string
    is_standard_clause?: boolean
  },
  onUploadProgress?: (percent: number) => void,
) {
  const form = new FormData()
  form.append('file', payload.file)
  if (payload.title) form.append('title', payload.title)
  if (payload.doc_kind) form.append('doc_kind', payload.doc_kind)
  if (payload.scheme_type) form.append('scheme_type', payload.scheme_type)
  if (payload.is_standard_clause !== undefined) {
    form.append('is_standard_clause', String(payload.is_standard_clause))
  }
  return apiClient.post<DocumentUploadResponse>(`/knowledge-bases/${kbId}/documents`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
    onUploadProgress(event) {
      if (!onUploadProgress || !event.total) return
      onUploadProgress(Math.round((event.loaded / event.total) * 100))
    },
  })
}

export function listDocuments(
  kbId: string,
  params: { page?: number; page_size?: number; search?: string; status?: string },
) {
  return apiClient.get<DocumentListResponse>(`/knowledge-bases/${kbId}/documents`, { params })
}

export function getDocument(documentId: string) {
  return apiClient.get<DocumentDetailResponse>(`/documents/${documentId}`)
}

export function getIngestProgress(documentId: string) {
  return apiClient.get<IngestJobProgress>(`/documents/${documentId}/progress`)
}

export function retryDocument(documentId: string) {
  return apiClient.post<{ document_id: string; job_id: string; trace_id: string; status: string }>(
    `/documents/${documentId}/retry`,
  )
}

export function disableDocument(documentId: string) {
  return apiClient.delete<DocumentOut>(`/documents/${documentId}`)
}
