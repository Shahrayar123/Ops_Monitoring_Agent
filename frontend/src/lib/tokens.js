// Where the JWT pair lives between page loads. localStorage keeps the user
// signed in across refreshes; clearing it is a full logout.
const ACCESS = 'ops.access'
const REFRESH = 'ops.refresh'

export const tokenStore = {
  get access() {
    return localStorage.getItem(ACCESS)
  },
  get refresh() {
    return localStorage.getItem(REFRESH)
  },
  set({ access_token, refresh_token }) {
    localStorage.setItem(ACCESS, access_token)
    localStorage.setItem(REFRESH, refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
  },
}
