export interface UserProfile {
  id: string
  username: string
  display_name: string
  role: string
  require_password_change: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: UserProfile
}

export interface UserProfileDetail {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  require_password_change: boolean
  avatar_url: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminUserOut {
  id: string
  username: string
  display_name: string
  role: string
  is_active: boolean
  require_password_change: boolean
  avatar_url: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminUserListResponse {
  items: AdminUserOut[]
  total: number
  page: number
  page_size: number
}

export interface AdminCreateUserRequest {
  username: string
  display_name: string
  password: string
  role?: string
}

export interface AdminUpdateUserRequest {
  display_name?: string
  role?: string
  is_active?: boolean
  require_password_change?: boolean
}

export interface AuditLogOut {
  id: string
  actor_user_id: string | null
  action: string
  target_type: string
  target_id: string | null
  ip_address: string
  details: Record<string, unknown>
  created_at: string
}

export interface AuditLogListResponse {
  items: AuditLogOut[]
  total: number
  page: number
  page_size: number
}
