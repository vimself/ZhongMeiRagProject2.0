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
