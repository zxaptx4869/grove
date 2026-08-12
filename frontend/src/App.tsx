import { lazy, Suspense } from 'react'
import { Link, Route, Routes } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { HealthPage } from '@/pages/HealthPage'
import { HomePage } from '@/pages/HomePage'

// 基座示例页按需加载，避免把 cmdk/react-markdown 等打进首屏主包
const BasicsPage = lazy(() =>
  import('@/pages/BasicsPage').then((module) => ({ default: module.BasicsPage })),
)

/**
 * 应用根组件：全局布局 + 路由。
 * 布局采用流式 + max-w 容器，保证 390px 移动宽度下不横向溢出。
 */
export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b">
        <nav className="mx-auto flex w-full max-w-5xl items-center gap-6 px-4 py-3">
          <Link to="/" className="font-semibold">
            知林 Grove
          </Link>
          <Link to="/health" className="text-sm text-muted-foreground hover:text-foreground">
            健康检查
          </Link>
          <Link to="/basics" className="text-sm text-muted-foreground hover:text-foreground">
            组件基座
          </Link>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route
            path="/basics"
            element={
              <Suspense fallback={<p className="text-body-sm text-muted-foreground">加载中…</p>}>
                <BasicsPage />
              </Suspense>
            }
          />
        </Routes>
      </main>
      {/* Sonner 全局提示：主题跟随设计令牌（richColors 使用语义色） */}
      <Toaster position="bottom-right" richColors />
    </div>
  )
}
