import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useMe } from '@/hooks/useAuth'

export interface ProtectedRouteProps {
  children: ReactNode
}

/** 路由守卫：未登录（/api/me 401）时重定向到登录页。 */
export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const me = useMe()

  if (me.isLoading) {
    return <p className="text-body-sm text-muted-foreground">正在加载…</p>
  }
  if (me.isError) {
    return <Navigate to="/login" replace />
  }
  return children
}
