import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

interface RetryRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

interface AuthHandlers {
  getAccessToken: () => string | null
  getRefreshToken: () => string | null
  refresh: () => Promise<boolean>
  clear: () => void
}

let authHandlers: AuthHandlers = {
  getAccessToken: () => null,
  getRefreshToken: () => null,
  refresh: async () => false,
  clear: () => undefined,
}

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v2',
  timeout: 15_000,
})

export function configureAuthHandlers(handlers: AuthHandlers) {
  authHandlers = handlers
}

apiClient.interceptors.request.use((config) => {
  const accessToken = authHandlers.getAccessToken()
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const response = error.response
    const originalRequest = error.config as RetryRequestConfig | undefined
    const url = originalRequest?.url ?? ''
    if (
      !response ||
      !originalRequest ||
      response.status !== 401 ||
      originalRequest._retry ||
      url.includes('/auth/login') ||
      url.includes('/auth/refresh')
    ) {
      return Promise.reject(error)
    }

    if (!authHandlers.getRefreshToken()) {
      authHandlers.clear()
      return Promise.reject(error)
    }

    originalRequest._retry = true
    const refreshed = await authHandlers.refresh()
    if (!refreshed) {
      authHandlers.clear()
      return Promise.reject(error)
    }
    originalRequest.headers.Authorization = `Bearer ${authHandlers.getAccessToken()}`
    return apiClient(originalRequest)
  },
)
