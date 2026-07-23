import { api } from './api'

export const tenantAdminApi = {
  async create(body) {
    return (await api.post('/admin/tenants', body)).data
  },
  async update(slug, body) {
    return (await api.patch(`/admin/tenants/${slug}`, body)).data
  },
  async setConnection(slug, body) {
    return (await api.put(`/admin/tenants/${slug}/connection`, body)).data
  },
  async testConnection(slug, body) {
    return (await api.post(`/admin/tenants/${slug}/test-connection`, body || null)).data
  },
  async uploadFile(slug, fileType, file) {
    const form = new FormData()
    form.append('file_type', fileType)
    form.append('file', file)
    return (await api.post(`/admin/tenants/${slug}/files`, form)).data
  },
  async deleteFile(slug, fileId) {
    await api.delete(`/admin/tenants/${slug}/files/${fileId}`)
  },
  async linkUser(slug, userId) {
    await api.post(`/admin/tenants/${slug}/link/${userId}`)
  },
  async unlinkUser(slug, userId) {
    await api.delete(`/admin/tenants/${slug}/link/${userId}`)
  },
  async linkedUsers(slug) {
    return (await api.get(`/admin/tenants/${slug}/users`)).data
  },
}

export const FILE_TYPES = [
  { key: 'hosts', label: 'Hosts', hint: 'host resource files (health, heartbeat)', required: true },
  { key: 'cpu', label: 'CPU metrics', hint: 'cpu.json', required: true },
  { key: 'ram', label: 'Memory metrics', hint: 'ram.json', required: true },
  { key: 'disk', label: 'Disk metrics', hint: 'disk.json', required: true },
  { key: 'hdfs', label: 'HDFS metrics', hint: 'hdfs.json', required: true },
  { key: 'network', label: 'Network metrics', hint: 'network.json', required: true },
  { key: 'services', label: 'Services', hint: 'services.json (optional)', required: false },
  { key: 'events', label: 'Events / alerts', hint: 'events.json (optional)', required: false },
]
