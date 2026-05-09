import { apiClient } from '@/api/client'
import type {
  KnowledgeBaseCreateRequest,
  KnowledgeBaseListResponse,
  KnowledgeBaseOut,
  KnowledgeBaseUpdateRequest,
  PermissionOut,
  PermissionUpdateRequest,
  PermissionUserOut,
} from '@/api/types'

export function listKnowledgeBases(params: { page?: number; page_size?: number; search?: string }) {
  return apiClient.get<KnowledgeBaseListResponse>('/knowledge-bases', { params })
}

export function createKnowledgeBase(data: KnowledgeBaseCreateRequest) {
  return apiClient.post<KnowledgeBaseOut>('/knowledge-bases', data)
}

export function getKnowledgeBase(kbId: string) {
  return apiClient.get<KnowledgeBaseOut>(`/knowledge-bases/${kbId}`)
}

export function updateKnowledgeBase(kbId: string, data: KnowledgeBaseUpdateRequest) {
  return apiClient.put<KnowledgeBaseOut>(`/knowledge-bases/${kbId}`, data)
}

export function disableKnowledgeBase(kbId: string) {
  return apiClient.delete<KnowledgeBaseOut>(`/knowledge-bases/${kbId}`)
}

export function listPermissions(kbId: string) {
  return apiClient.get<PermissionOut[]>(`/knowledge-bases/${kbId}/permissions`)
}

export function listPermissionCandidates(kbId: string, params?: { search?: string }) {
  return apiClient.get<PermissionUserOut[]>(`/knowledge-bases/${kbId}/permission-candidates`, {
    params,
  })
}

export function updatePermissions(kbId: string, data: PermissionUpdateRequest) {
  return apiClient.put<PermissionOut[]>(`/knowledge-bases/${kbId}/permissions`, data)
}

// ── Admin ──────────────────────────────────────────────────────────────

export function adminListKnowledgeBases(params: {
  page?: number
  page_size?: number
  search?: string
  is_active?: boolean
}) {
  return apiClient.get<KnowledgeBaseListResponse>('/admin/knowledge-bases', { params })
}

export function adminListPermissions(kbId: string) {
  return apiClient.get<PermissionOut[]>(`/admin/knowledge-bases/${kbId}/permissions`)
}
