import { api } from './api'

export const kpiSettingsApi = {
  async list() {
    return (await api.get('/settings/kpi-refresh')).data
  },
  async set(task, seconds) {
    return (await api.put('/settings/kpi-refresh', { task, seconds })).data
  },
  async reset(task) {
    return (await api.delete(`/settings/kpi-refresh/${task}`)).data
  },
}
