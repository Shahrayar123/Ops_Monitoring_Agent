import { api } from './api'

// Metadata for each of the nine checks — display name + icon, mirroring the
// original dashboard so the product reads consistently.
export const CHECK_META = {
  host_health: { label: 'Host Health', icon: '🖥️' },
  heartbeat: { label: 'Heartbeat', icon: '💓' },
  cpu_percent: { label: 'CPU Utilization', icon: '⚙️' },
  ram_percent: { label: 'Memory Utilization', icon: '🧠' },
  disk_percent: { label: 'Disk & Logs', icon: '💾' },
  hdfs_health: { label: 'HDFS Capacity & Health', icon: '🗄️' },
  service_status: { label: 'Service & Role Status', icon: '🧩' },
  alerts: { label: 'Cluster Alerts', icon: '🚨' },
  network: { label: 'Network & Connectivity', icon: '🌐' },
}

export const monitoringApi = {
  async listTenants() {
    return (await api.get('/tenants')).data
  },
  async getTenant(slug) {
    return (await api.get(`/tenants/${slug}`)).data
  },
  async dates(slug) {
    return (await api.get(`/tenants/${slug}/dates`)).data.dates
  },
  async report(slug, asOf) {
    return (await api.get(`/tenants/${slug}/report`, { params: asOf ? { as_of: asOf } : {} })).data
  },
  async check(slug, task, asOf) {
    return (await api.get(`/tenants/${slug}/report/${task}`, { params: asOf ? { as_of: asOf } : {} })).data
  },
  async getThresholds(slug) {
    return (await api.get(`/tenants/${slug}/thresholds`)).data
  },
  async updateThresholds(slug, changes) {
    return (await api.put(`/tenants/${slug}/thresholds`, changes)).data
  },
}
