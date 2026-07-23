import { api } from './api'

export const analysisApi = {
  async startKpi(slug, task, asOf) {
    return (await api.post(`/tenants/${slug}/analyze/${task}`, null, { params: asOf ? { as_of: asOf } : {} })).data
  },
  async startIncident(slug, asOf) {
    return (await api.post(`/tenants/${slug}/analyze`, null, { params: asOf ? { as_of: asOf } : {} })).data
  },
  async poll(jobId) {
    return (await api.get(`/analysis/${jobId}`)).data
  },
  async dependencies(slug) {
    return (await api.get(`/tenants/${slug}/dependencies`)).data
  },
}
