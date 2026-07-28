import { createContext, useContext, useEffect, useState } from 'react'
import { authApi } from './authApi'
import { tokenStore } from './tokens'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true) // true while restoring the session

  // On first load, if a token exists, fetch the account so a refresh keeps you
  // logged in. A failed /me (expired/revoked) simply lands you on login.
  useEffect(() => {
    let active = true
    async function restore() {
      if (!tokenStore.access) {
        setLoading(false)
        return
      }
      try {
        const me = await authApi.me()
        if (active) setUser(me)
      } catch {
        tokenStore.clear()
      } finally {
        if (active) setLoading(false)
      }
    }
    restore()
    return () => {
      active = false
    }
  }, [])

  async function login(email, password) {
    await authApi.login(email, password)
    setUser(await authApi.me())
  }

  async function logout() {
    await authApi.logout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, setUser, loading, login, logout, isAdmin: user?.role === 'admin' }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
