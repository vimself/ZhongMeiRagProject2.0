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

// ── Knowledge Base ─────────────────────────────────────────────────

export interface KnowledgeBaseOut {
  id: string
  name: string
  description: string
  creator_id: string | null
  creator_username: string
  creator_name: string
  is_active: boolean
  my_role: string | null
  document_count: number
  active_document_count: number
  permission_count: number
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseListResponse {
  items: KnowledgeBaseOut[]
  total: number
  page: number
  page_size: number
}

export interface KnowledgeBaseCreateRequest {
  name: string
  description?: string
}

export interface KnowledgeBaseUpdateRequest {
  name?: string
  description?: string
}

export interface PermissionOut {
  id: string
  knowledge_base_id: string
  user_id: string
  username: string
  display_name: string
  role: string
  created_at: string
  updated_at: string
}

export interface PermissionUserOut {
  id: string
  username: string
  display_name: string
}

export interface PermissionUpdateItem {
  user_id: string
  role: string
}

export interface PermissionUpdateRequest {
  permissions: PermissionUpdateItem[]
}

// ── Documents / Ingest ──────────────────────────────────────────────

export interface DocumentOut {
  id: string
  knowledge_base_id: string
  uploader_id: string
  uploader_name: string
  title: string
  filename: string
  mime: string
  size_bytes: number
  sha256: string
  doc_kind: string
  scheme_type: string | null
  is_standard_clause: boolean
  status: string
  page_count: number | null
  created_at: string
  updated_at: string
}

export interface DocumentListResponse {
  items: DocumentOut[]
  total: number
  page: number
  page_size: number
}

export interface DocumentUploadResponse {
  document_id: string
  job_id: string
  trace_id: string
}

export interface IngestStepProgress {
  step: string
  status: string
  created_at: string | null
}

export interface IngestJobProgress {
  document_id: string
  job_id: string | null
  job_status: string | null
  document_status: string
  progress: number
  steps: IngestStepProgress[]
  last_error: string | null
}

export interface AssetOut {
  id: string
  kind: string
  page_no: number | null
  bbox: Record<string, unknown> | null
  storage_path: string
  url: string | null
  caption: string | null
  created_at: string
}

export interface DocumentDetailResponse extends DocumentOut {
  latest_job: Record<string, unknown> | null
  parse_result: Record<string, unknown> | null
  assets: AssetOut[]
}
