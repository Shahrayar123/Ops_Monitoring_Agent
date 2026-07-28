import axios from 'axios'
import { tokenStore } from './tokens'

// All calls go to /api/* which Vite (dev) or the reverse proxy (prod) forwards
// to the FastAPI backend — so the frontend never hardcodes a backend host.
export const api = axios.create({ baseURL: '/api' })

// --- attach the access token to every request ---
api.interceptors.request.use((config) => {
  const token = tokenStore.access
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// --- on 401, transparently refresh once and replay the request ---
// A single in-flight refresh is shared by all requests that 401 at once, so a
// burst of calls after the access token expires triggers exactly one refresh.
let refreshing = null

function onLoggedOut() {
  tokenStore.clear()
  // Full reload to the login route clears all in-memory state cleanly.
  if (!window.location.pathname.startsWith('/login')) {
    window.location.assign('/login?expired=1')
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    const status = error.response?.status

    // Don't try to refresh the refresh call itself, or retry twice.
    const isAuthCall = original?.url?.includes('/auth/login') || original?.url?.includes('/auth/refresh')

    if (status === 401 && !original._retried && !isAuthCall) {
      original._retried = true
      try {
        if (!refreshing) {
          refreshing = api
            .post('/auth/refresh', { refresh_token: tokenStore.refresh })
            .then((r) => {
              tokenStore.set(r.data)
              return r.data.access_token
            })
            .finally(() => {
              refreshing = null
            })
        }
        const newAccess = await refreshing
        original.headers.Authorization = `Bearer ${newAccess}`
        return api(original)
      } catch {
        onLoggedOut()
      }
    }
    // Reject with the raw axios error, unchanged — every call site normalizes
    // it exactly once via normalizeError(). Normalizing here too would strip
    // error.response before call sites see it, so real backend messages (4xx/5xx)
    // would collapse into the generic "Cannot reach the server" fallback.
    return Promise.reject(error)
  }
)

// Unwrap the backend's { error: { code, message, request_id } } envelope into a
// flat, predictable shape the UI can rely on.
//
// Message precedence:
//  1. A real backend envelope message (every backend response — 4xx AND 5xx —
//     carries one via install_error_handling), so use it verbatim.
//  2. No response at all (axios network error) → the request never left, backend
//     unreachable.
//  3. A response WITHOUT our envelope on a 5xx status → it didn't come from our
//     backend; it's the dev proxy / gateway failing to reach it (e.g. backend
//     process is down → ECONNREFUSED → proxy returns a bare 500). Same cause.
//  4. Anything else → genuinely unexpected.
const UNREACHABLE = 'Cannot reach the server. Is the backend running?'

export function normalizeError(error) {
  const env = error.response?.data?.error
  const status = error.response?.status ?? 0
  let message = env?.message
  if (!message) {
    if (!error.response) message = UNREACHABLE
    else if (status >= 500) message = UNREACHABLE   // envelope-less 5xx = proxy couldn't reach the backend
    else message = 'Something went wrong.'
  }
  return {
    status,
    code: env?.code ?? 'network_error',
    message,
    requestId: env?.request_id,
    original: error,
  }
}
