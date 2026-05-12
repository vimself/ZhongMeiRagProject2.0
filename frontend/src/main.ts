import { createPinia } from 'pinia'
import { createApp } from 'vue'

import { configureAuthHandlers } from './api/client'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import 'element-plus/theme-chalk/el-overlay.css'
import './styles/base.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

const auth = useAuthStore()
configureAuthHandlers({
  getAccessToken: () => auth.accessToken,
  getRefreshToken: () => auth.refreshToken,
  refresh: () => auth.refresh(),
  clear: () => auth.clearSession(),
})

app.use(router)

app.mount('#app')
