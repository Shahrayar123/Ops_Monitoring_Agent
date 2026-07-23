import { api } from './api'

export const llmApi = {
  async getSettings() {
    return (await api.get('/settings/llm')).data
  },
  async setPriority(model_ids) {
    return (await api.post('/settings/llm/priority', { model_ids })).data
  },
  async setOllamaUrl(url) {
    return (await api.post('/settings/llm/ollama-url', { url })).data
  },
  async setKey(provider, api_key) {
    return (await api.put('/settings/llm/keys', { provider, api_key })).data
  },
  async deleteKey(provider) {
    return (await api.delete(`/settings/llm/keys/${provider}`)).data
  },
  async testModel(model_id) {
    return (await api.post('/settings/llm/test', { model_id })).data
  },
}

export const plansApi = {
  async list() {
    return (await api.get('/admin/plans')).data
  },
  async catalog() {
    return (await api.get('/admin/catalog')).data
  },
  async create(body) {
    return (await api.post('/admin/plans', body)).data
  },
  async update(id, body) {
    return (await api.patch(`/admin/plans/${id}`, body)).data
  },
  async remove(id) {
    await api.delete(`/admin/plans/${id}`)
  },
  async assign(userId, planId) {
    await api.post(`/admin/users/${userId}/plan`, { plan_id: planId })
  },
  async usage() {
    return (await api.get('/admin/usage')).data
  },
}

export const userAdminApi = {
  async create(body) {
    return (await api.post('/admin/users/create', body)).data
  },
  async detail(userId) {
    return (await api.get(`/admin/users/${userId}/detail`)).data
  },
  async setAccess(userId, body) {
    return (await api.patch(`/admin/users/${userId}/access`, body)).data
  },
  async clusters(userId) {
    return (await api.get(`/admin/users/${userId}/clusters`)).data
  },
  async setClusters(userId, tenant_slugs) {
    return (await api.put(`/admin/users/${userId}/clusters`, { tenant_slugs })).data
  },
  async remove(userId) {
    await api.delete(`/admin/users/${userId}`)
  },
  async acceptDeletion(userId) {
    return (await api.post(`/admin/users/${userId}/deletion/accept`)).data
  },
  async rejectDeletion(userId) {
    return (await api.post(`/admin/users/${userId}/deletion/reject`)).data
  },
  async approveRecovery(userId) {
    return (await api.post(`/admin/users/${userId}/recovery/approve`)).data
  },
  async rejectRecovery(userId) {
    return (await api.post(`/admin/users/${userId}/recovery/reject`)).data
  },
}
