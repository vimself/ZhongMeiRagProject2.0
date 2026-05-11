import { defineStore } from 'pinia'

import type { DocTypeCount, HotKeyword, SchemeTypeCount, SearchHit } from '@/api/search'
import {
  createExportJob,
  fetchDocTypes,
  fetchHotKeywords,
  getExportJobStatus,
  searchDocuments,
} from '@/api/search'

export const useSearchStore = defineStore('search', {
  state: () => ({
    query: '',
    kbId: null as string | null,
    docKind: null as string | null,
    schemeType: null as string | null,
    results: [] as SearchHit[],
    total: 0,
    page: 1,
    pageSize: 20,
    sortBy: 'relevance',
    loading: false,
    error: null as string | null,
    hotKeywords: [] as HotKeyword[],
    docKinds: [] as DocTypeCount[],
    schemeTypes: [] as SchemeTypeCount[],
    exportJobId: null as string | null,
    exportStatus: null as string | null,
    exportDownloadUrl: null as string | null,
    exportPolling: false,
    hasSearched: false,
  }),

  actions: {
    async search() {
      this.loading = true
      this.error = null
      this.hasSearched = true
      try {
        const params: Record<string, unknown> = {
          query: this.query,
          page: this.page,
          page_size: this.pageSize,
          sort_by: this.sortBy,
        }
        if (this.kbId) params.kb_id = this.kbId
        if (this.docKind) params.doc_kind = this.docKind
        if (this.schemeType) params.scheme_type = this.schemeType

        const { data } = await searchDocuments(params as never)
        this.results = data.items
        this.total = data.total
      } catch (err: unknown) {
        const e = err as { response?: { data?: { detail?: string } } }
        this.error = e.response?.data?.detail ?? '搜索失败'
        this.results = []
        this.total = 0
      } finally {
        this.loading = false
      }
    },

    async loadHotKeywords() {
      try {
        const { data } = await fetchHotKeywords(20)
        this.hotKeywords = data.items
      } catch {
        this.hotKeywords = []
      }
    },

    async loadDocTypes() {
      try {
        const { data } = await fetchDocTypes()
        this.docKinds = data.doc_kinds
        this.schemeTypes = data.scheme_types
      } catch {
        this.docKinds = []
        this.schemeTypes = []
      }
    },

    async startExport(format: string = 'json') {
      this.exportPolling = true
      this.exportStatus = null
      this.exportDownloadUrl = null
      try {
        const params: Record<string, unknown> = {
          query: this.query,
          format,
        }
        if (this.kbId) params.kb_id = this.kbId
        if (this.docKind) params.doc_kind = this.docKind
        if (this.schemeType) params.scheme_type = this.schemeType

        const { data } = await createExportJob(params as never)
        this.exportJobId = data.job_id
        this.exportStatus = data.status
      } catch {
        this.exportStatus = 'failed'
        this.exportPolling = false
      }
    },

    async pollExportStatus() {
      if (!this.exportJobId) return
      try {
        const { data } = await getExportJobStatus(this.exportJobId)
        this.exportStatus = data.status
        this.exportDownloadUrl = data.download_url
        if (data.status === 'succeeded' || data.status === 'failed') {
          this.exportPolling = false
        }
      } catch {
        this.exportPolling = false
      }
    },

    applyKeyword(keyword: string) {
      this.query = keyword
      this.page = 1
      this.search()
    },

    applyDocKind(kind: string) {
      this.docKind = this.docKind === kind ? null : kind
      this.page = 1
      this.search()
    },

    resetFilters() {
      this.query = ''
      this.kbId = null
      this.docKind = null
      this.schemeType = null
      this.page = 1
      this.sortBy = 'relevance'
      this.results = []
      this.total = 0
      this.hasSearched = false
      this.error = null
    },
  },
})
