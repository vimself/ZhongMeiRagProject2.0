import { apiClient } from '@/api/client'
import type { UserProfileDetail } from '@/api/types'

export function getProfile() {
  return apiClient.get<UserProfileDetail>('/user/profile')
}

export function updateProfile(display_name: string) {
  return apiClient.put<UserProfileDetail>('/user/profile', { display_name })
}

export function uploadAvatar(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return apiClient.post<UserProfileDetail>('/user/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteAvatar() {
  return apiClient.delete<UserProfileDetail>('/user/avatar')
}

export function changePasswordViaUser(old_password: string, new_password: string) {
  return apiClient.post('/user/change-password', { old_password, new_password })
}
