import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useLogout, useMe } from '@/hooks/useAuth'

const NAV_ITEMS = [
  { to: '/projects', label: '项目' },
  { to: '/inbox', label: '采集' },
  { to: '/search', label: '搜索' },
] as const

function navClassName({ isActive }: { isActive: boolean }) {
  return [
    'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium',
    isActive
      ? 'bg-muted text-foreground'
      : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground',
  ].join(' ')
}

/**
 * 应用壳：桌面左侧全局导航 + 右侧内容区（移动端为顶部导航），
 * 布局参考 KnowStruct（Grove 在其基础上升级）。
 */
export function AppShell() {
  const me = useMe()
  const logout = useLogout()
  const navigate = useNavigate()

  async function handleLogout() {
    try {
      await logout.mutateAsync()
      toast.success('已退出登录')
      navigate('/login', { replace: true })
    } catch {
      toast.error('退出失败，请重试')
    }
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      {/* 桌面侧边栏 */}
      <aside className="hidden w-56 shrink-0 flex-col border-r md:flex">
        <Link to="/projects" className="px-4 py-4 font-semibold">
          知林 Grove
        </Link>
        <nav className="flex-1 space-y-1 px-2" aria-label="全局导航">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className={navClassName}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t p-3">
          {me.data ? (
            <p className="truncate text-body-sm text-muted-foreground">
              {me.data.user.username}
            </p>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={handleLogout}
            disabled={logout.isPending}
          >
            {logout.isPending ? '退出中…' : '退出登录'}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 移动端顶栏 */}
        <header className="border-b px-4 py-3 md:hidden">
          <div className="flex items-center justify-between">
            <Link to="/projects" className="font-semibold">
              知林 Grove
            </Link>
            {me.data ? (
              <Button variant="outline" size="sm" onClick={handleLogout} disabled={logout.isPending}>
                {logout.isPending ? '退出中…' : '退出'}
              </Button>
            ) : null}
          </div>
          <nav className="mt-2 flex gap-4 overflow-x-auto" aria-label="全局导航">
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClassName}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main className="flex-1 px-4 py-6 md:px-6 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
