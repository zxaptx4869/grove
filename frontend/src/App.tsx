import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { Toaster } from '@/components/ui/sonner'
import { HealthPage } from '@/pages/HealthPage'

// 业务页面按需加载，避免首屏主包过大
const ProjectsPage = lazy(() =>
  import('@/pages/ProjectsPage').then((module) => ({ default: module.ProjectsPage })),
)
const ProjectPage = lazy(() =>
  import('@/pages/ProjectPage').then((module) => ({ default: module.ProjectPage })),
)
const InboxPage = lazy(() =>
  import('@/pages/InboxPage').then((module) => ({ default: module.InboxPage })),
)
const SearchPage = lazy(() =>
  import('@/pages/SearchPage').then((module) => ({ default: module.SearchPage })),
)
const LoginPage = lazy(() =>
  import('@/pages/LoginPage').then((module) => ({ default: module.LoginPage })),
)
const RegisterPage = lazy(() =>
  import('@/pages/RegisterPage').then((module) => ({ default: module.RegisterPage })),
)
const BasicsPage = lazy(() =>
  import('@/pages/BasicsPage').then((module) => ({ default: module.BasicsPage })),
)

function PageFallback() {
  return <p className="text-body-sm text-muted-foreground">加载中…</p>
}

/**
 * 应用根组件：登录/注册为独立全屏页；登录后进入应用壳
 * （桌面左侧导航 + 右侧内容区，参考 KnowStruct 布局）。
 */
export default function App() {
  return (
    <>
      <Routes>
        <Route
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route path="/projects" element={<Suspense fallback={<PageFallback />}><ProjectsPage /></Suspense>} />
          <Route path="/projects/:projectId" element={<Suspense fallback={<PageFallback />}><ProjectPage /></Suspense>} />
          <Route path="/inbox" element={<Suspense fallback={<PageFallback />}><InboxPage /></Suspense>} />
          <Route path="/search" element={<Suspense fallback={<PageFallback />}><SearchPage /></Suspense>} />
        </Route>

        <Route path="/login" element={<Suspense fallback={<PageFallback />}><LoginPage /></Suspense>} />
        <Route path="/register" element={<Suspense fallback={<PageFallback />}><RegisterPage /></Suspense>} />

        {/* 开发调试页：不进产品导航，可直接访问 */}
        <Route path="/health" element={<HealthPage />} />
        <Route path="/basics" element={<Suspense fallback={<PageFallback />}><BasicsPage /></Suspense>} />

        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
      {/* Sonner 全局提示：主题跟随设计令牌（richColors 使用语义色） */}
      <Toaster position="bottom-right" richColors />
    </>
  )
}
