import { apiClient } from '@/api/client'

export interface PdfSignResponse {
  token: string
  expires_at: string
  document_id: string
}

export interface AssetSignResponse {
  token: string
  expires_at: string
  asset_id: string
  document_id: string
  url: string
}

export function signPdfToken(documentId: string) {
  return apiClient.post<PdfSignResponse>('/pdf/sign', { document_id: documentId })
}

export function signAssetToken(assetId: string) {
  return apiClient.post<AssetSignResponse>('/assets/sign', { asset_id: assetId })
}

export function pdfPreviewUrl(documentId: string, token: string, page?: number): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? '/api/v2'
  const params = new URLSearchParams({ document_id: documentId, token })
  if (page !== undefined) {
    params.set('page', String(page))
  }
  return `${base}/pdf/preview?${params.toString()}`
}
