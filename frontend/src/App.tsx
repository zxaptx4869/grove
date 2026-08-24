import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { AuthLayout } from '@/components/layout/AuthLayout'
import { ProtectedRoute } from '@/components/auth/ProtectedRoute'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { HealthPage } from '@/pages/HealthPage'

// 业务页面按需加载，避免首屏主包过大
const ProjectsPage = lazy(() =>
  import('@/pages/ProjectsPage').then((module) => ({ default: module.ProjectsPage })),
)
const ProjectPage = lazy(() =>
  import('@/pages/ProjectPage').then((module) => ({ default: module.ProjectPage })),
)
const ReviewPage = lazy(() =>
  import('@/pages/ReviewPage').then((module) => ({ default: module.ReviewPage })),
)
const InboxPage = lazy(() =>
  import('@/pages/InboxPage').then((module) => ({ default: module.InboxPage })),
)
const SourceHistoryPage = lazy(() =>
  import('@/pages/SourceHistoryPage').then((module) => ({ default: module.SourceHistoryPage })),
)
const SearchPage = lazy(() =>
  import('@/pages/SearchPage').then((module) => ({ default: module.SearchPage })),
)
const AISettingsPage = lazy(() =>
  import('@/pages/AISettingsPage').then((module) => ({ default: module.AISettingsPage })),
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
  return <div className="mx-auto max-w-6xl py-16 text-body-sm text-muted-foreground" role="status">加载中…</div>
}

function DesktopBoundary({ children }: { children: ReactNode }) {
  const [blocked, setBlocked] = useState(() => window.innerWidth < 1024)
  useEffect(() => {
    const update = () => setBlocked(window.innerWidth < 1024)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  if (blocked) return <main className="flex min-h-screen items-center justify-center bg-muted/30 px-6"><div className="max-w-md text-center"><div className="mx-auto mb-5 flex size-12 items-center justify-center rounded-xl bg-foreground text-background">G</div><h1 className="text-heading font-semibold">请在电脑端打开 Grove</h1><p className="mt-2 text-body-sm leading-6 text-muted-foreground">Grove 是面向桌面的知识整理工作台，当前浏览器宽度不足以安全完成项目和目录管理。</p></div></main>
  return <>{children}</>
}

/**
 * 应用根组件：登录/注册为独立全屏页；登录后进入应用壳
 * （桌面左侧导航 + 右侧内容区，参考 KnowStruct 布局）。
 */
export default function App() {
  return (
    <DesktopBoundary><TooltipProvider>
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
          <Route path="/projects/:projectId/review" element={<Suspense fallback={<PageFallback />}><ReviewPage /></Suspense>} />
          <Route path="/inbox" element={<Suspense fallback={<PageFallback />}><InboxPage /></Suspense>} />
          <Route path="/sources" element={<Suspense fallback={<PageFallback />}><SourceHistoryPage /></Suspense>} />
          <Route path="/search" element={<Suspense fallback={<PageFallback />}><SearchPage /></Suspense>} />
          <Route path="/settings/ai" element={<Suspense fallback={<PageFallback />}><AISettingsPage /></Suspense>} />
        </Route>

        <Route path="/login" element={<AuthLayout><Suspense fallback={<PageFallback />}><LoginPage /></Suspense></AuthLayout>} />
        <Route path="/register" element={<AuthLayout><Suspense fallback={<PageFallback />}><RegisterPage /></Suspense></AuthLayout>} />

        {/* 开发调试页：不进产品导航，可直接访问 */}
        <Route path="/health" element={<HealthPage />} />
        <Route path="/basics" element={<Suspense fallback={<PageFallback />}><BasicsPage /></Suspense>} />

        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Routes>
      {/* Sonner 全局提示：主题跟随设计令牌（richColors 使用语义色） */}
      <Toaster position="top-center" richColors />
    </TooltipProvider></DesktopBoundary>
  )
}
