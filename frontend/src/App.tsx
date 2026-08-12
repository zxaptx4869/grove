import { Link, Route, Routes } from 'react-router-dom'
import { HealthPage } from '@/pages/HealthPage'
import { HomePage } from '@/pages/HomePage'

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
          <Link
            to="/health"
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            健康检查
          </Link>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/health" element={<HealthPage />} />
        </Routes>
      </main>
    </div>
  )
}
