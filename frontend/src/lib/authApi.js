import { api } from './api'
import { tokenStore } from './tokens'

// Thin typed wrappers over the backend auth endpoints.
export const authApi = {
  async login(email, password) {
    const { data } = await api.post('/auth/login', { email, password })
    tokenStore.set(data)
    return data
  },
  async register({ email, password, full_name }) {
    const { data } = await api.post('/auth/register', { email, password, full_name })
    return data
  },
  async me() {
    const { data } = await api.get('/auth/me')
    return data
  },
  async changePassword(current_password, new_password) {
    await api.post('/auth/change-password', { current_password, new_password })
  },
  async requestDeletion() {
    const { data } = await api.post('/auth/request-deletion')
    return data
  },
  async cancelDeletionRequest() {
    const { data } = await api.post('/auth/cancel-deletion-request')
    return data
  },
  async recoverAccount(email, password) {
    const { data } = await api.post('/auth/recover', { email, password })
    return data
  },
  async logout() {
    try {
      if (tokenStore.refresh) {
        await api.post('/auth/logout', { refresh_token: tokenStore.refresh })
      }
    } finally {
      tokenStore.clear()
    }
  },
}
