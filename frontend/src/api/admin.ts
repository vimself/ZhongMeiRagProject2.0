import { apiClient } from '@/api/client'
import type {
  AdminCreateUserRequest,
  AdminUpdateUserRequest,
  AdminUserListResponse,
  AdminUserOut,
  AuditLogListResponse,
} from '@/api/types'

export function listUsers(params: {
  page?: number
  page_size?: number
  search?: string
  role?: string
  is_active?: boolean
}) {
  return apiClient.get<AdminUserListResponse>('/admin/users', { params })
}

export function createUser(data: AdminCreateUserRequest) {
  return apiClient.post<AdminUserOut>('/admin/users', data)
}

export function updateUser(userId: string, data: AdminUpdateUserRequest) {
  return apiClient.put<AdminUserOut>(`/admin/users/${userId}`, data)
}

export function resetPassword(userId: string, new_password: string) {
  return apiClient.post<AdminUserOut>(`/admin/users/${userId}/reset-password`, { new_password })
}

export function disableUser(userId: string) {
  return apiClient.delete<AdminUserOut>(`/admin/users/${userId}`)
}

export function listAuditLogs(params: {
  page?: number
  page_size?: number
  target_type?: string
  target_id?: string
  action?: string
}) {
  return apiClient.get<AuditLogListResponse>('/admin/audit-logs', { params })
}
