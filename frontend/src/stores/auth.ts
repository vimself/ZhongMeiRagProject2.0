import { defineStore } from 'pinia'

import { apiClient } from '@/api/client'
import type { TokenResponse, UserProfile } from '@/api/types'

const ACCESS_TOKEN_KEY = 'zhongmei.accessToken'
const REFRESH_TOKEN_KEY = 'zhongmei.refreshToken'
const USER_KEY = 'zhongmei.user'

function readUser(): UserProfile | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as UserProfile
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(ACCESS_TOKEN_KEY),
    refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
    user: readUser(),
    refreshing: null as Promise<boolean> | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.accessToken && state.user),
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    applySession(payload: TokenResponse) {
      this.accessToken = payload.access_token
      this.refreshToken = payload.refresh_token
      this.user = payload.user
      localStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token)
      localStorage.setItem(REFRESH_TOKEN_KEY, payload.refresh_token)
      localStorage.setItem(USER_KEY, JSON.stringify(payload.user))
    },
    clearSession() {
      this.accessToken = null
      this.refreshToken = null
      this.user = null
      localStorage.removeItem(ACCESS_TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    },
    async login(username: string, password: string) {
      const response = await apiClient.post<TokenResponse>('/auth/login', { username, password })
      this.applySession(response.data)
    },
    async refresh(): Promise<boolean> {
      if (!this.refreshToken) {
        return false
      }
      if (this.refreshing) {
        return this.refreshing
      }
      this.refreshing = apiClient
        .post<TokenResponse>('/auth/refresh', { refresh_token: this.refreshToken })
        .then((response) => {
          this.applySession(response.data)
          return true
        })
        .catch(() => {
          this.clearSession()
          return false
        })
        .finally(() => {
          this.refreshing = null
        })
      return this.refreshing
    },
    async logout() {
      const token = this.refreshToken
      this.clearSession()
      if (token) {
        await apiClient.post('/auth/logout', { refresh_token: token }).catch(() => undefined)
      }
    },
    async changePassword(oldPassword: string, newPassword: string) {
      await apiClient.post('/auth/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
      })
      if (this.user) {
        this.user = { ...this.user, require_password_change: false }
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      }
    },
    async refreshProfile() {
      const response = await apiClient.get('/user/profile')
      const profile = response.data
      if (this.user) {
        this.user = {
          ...this.user,
          display_name: profile.display_name,
          role: profile.role,
          require_password_change: profile.require_password_change,
        }
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      }
      return profile
    },
  },
})
