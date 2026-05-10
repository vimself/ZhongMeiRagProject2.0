import { ref } from 'vue'

import { pdfPreviewUrl, signPdfToken } from '@/api/pdfPreview'

export function usePdfPreview() {
  const pdfUrl = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const tokenExpiresAt = ref<string | null>(null)
  const currentPage = ref(1)
  const highlightBbox = ref<{
    page: number
    x: number
    y: number
    width: number
    height: number
  } | null>(null)

  async function openPreview(documentId: string, page?: number, bbox?: string) {
    loading.value = true
    error.value = null
    try {
      const { data } = await signPdfToken(documentId)
      pdfUrl.value = pdfPreviewUrl(data.document_id, data.token, page)
      tokenExpiresAt.value = data.expires_at
      if (page) {
        currentPage.value = page
      }
      if (bbox) {
        const parts = bbox.split(',').map(Number)
        if (parts.length === 4 && parts.every((n) => !isNaN(n))) {
          highlightBbox.value = {
            page: page ?? 1,
            x: parts[0],
            y: parts[1],
            width: parts[2],
            height: parts[3],
          }
        }
      }
    } catch {
      error.value = 'PDF 预览加载失败'
    } finally {
      loading.value = false
    }
  }

  function closePreview() {
    pdfUrl.value = null
    tokenExpiresAt.value = null
    highlightBbox.value = null
  }

  function onPageChange(page: number) {
    currentPage.value = page
  }

  return {
    pdfUrl,
    loading,
    error,
    tokenExpiresAt,
    currentPage,
    highlightBbox,
    openPreview,
    closePreview,
    onPageChange,
  }
}
