import { createRouter, createWebHistory } from 'vue-router'

import { getKnowledgeBase } from '@/api/knowledge'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('@/views/ProfileView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/AdminUsersView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('@/views/KnowledgeListView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/knowledge/:kbId/documents',
      name: 'knowledge-documents',
      component: () => import('@/views/KnowledgeDocumentsView.vue'),
      meta: { requiresAuth: true },
      beforeEnter: async (to) => {
        try {
          await getKnowledgeBase(String(to.params.kbId))
          return true
        } catch {
          return { name: 'knowledge' }
        }
      },
    },
    {
      path: '/admin/knowledge-bases',
      name: 'admin-knowledge-bases',
      component: () => import('@/views/AdminKnowledgeBasesView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    if (auth.refreshToken) {
      const refreshed = await auth.refresh()
      if (refreshed) {
        return true
      }
    }
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return { name: 'home' }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'home' }
  }
  return true
})

export default router
