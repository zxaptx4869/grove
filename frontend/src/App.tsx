import { lazy, Suspense } from 'react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { toast } from 'sonner'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { Button } from '@/components/ui/button'
import { Toaster } from '@/components/ui/sonner'
import { useLogout, useMe } from '@/hooks/useAuth'
import { HealthPage } from '@/pages/HealthPage'
import { HomePage } from '@/pages/HomePage'

// 基座示例页按需加载，避免把 cmdk/react-markdown 等打进首屏主包
const BasicsPage = lazy(() =>
  import('@/pages/BasicsPage').then((module) => ({ default: module.BasicsPage })),
)
const LoginPage = lazy(() =>
  import('@/pages/LoginPage').then((module) => ({ default: module.LoginPage })),
)
const RegisterPage = lazy(() =>
  import('@/pages/RegisterPage').then((module) => ({ default: module.RegisterPage })),
)
const ProjectsPage = lazy(() =>
  import('@/pages/ProjectsPage').then((module) => ({ default: module.ProjectsPage })),
)
const ProjectPage = lazy(() =>
  import('@/pages/ProjectPage').then((module) => ({ default: module.ProjectPage })),
)

/**
 * 应用根组件：全局布局 + 路由。
 * 布局采用流式 + max-w 容器，保证 390px 移动宽度下不横向溢出。
 */
export default function App() {
  const me = useMe()
  const logout = useLogout()

  async function handleLogout() {
    try {
      await logout.mutateAsync()
      toast.success('已退出登录')
    } catch {
      toast.error('退出失败，请重试')
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b">
        <nav className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link to="/" className="font-semibold">
            知林 Grove
          </Link>
          <Link to="/projects" className="text-sm text-muted-foreground hover:text-foreground">
            项目
          </Link>
          <Link to="/health" className="text-sm text-muted-foreground hover:text-foreground">
            健康检查
          </Link>
          <Link to="/basics" className="text-sm text-muted-foreground hover:text-foreground">
            组件基座
          </Link>
          <div className="ml-auto flex items-center gap-3">
            {me.data ? (
              <>
                <span className="text-body-sm text-muted-foreground">
                  {me.data.user.username}
                </span>
                <Button variant="outline" size="sm" onClick={handleLogout} disabled={logout.isPending}>
                  {logout.isPending ? '退出中…' : '退出登录'}
                </Button>
              </>
            ) : (
              <Link
                to="/login"
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                登录
              </Link>
            )}
          </div>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <HomePage />
              </ProtectedRoute>
            }
          />
          <Route path="/health" element={<HealthPage />} />
          <Route
            path="/basics"
            element={
              <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                <BasicsPage />
              </Suspense>
            }
          />
          <Route
            path="/login"
            element={
              <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                <LoginPage />
              </Suspense>
            }
          />
          <Route
            path="/register"
            element={
              <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                <RegisterPage />
              </Suspense>
            }
          />
          <Route
            path="/projects"
            element={
              <ProtectedRoute>
                <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                  <ProjectsPage />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route
            path="/projects/:projectId"
            element={
              <ProtectedRoute>
                <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                  <ProjectPage />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      {/* Sonner 全局提示：主题跟随设计令牌（richColors 使用语义色） */}
      <Toaster position="bottom-right" richColors />
    </div>
  )
}
