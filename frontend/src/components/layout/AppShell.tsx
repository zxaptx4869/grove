import { FolderKanban, Inbox, LogOut, Search, Settings2, Sparkles } from 'lucide-react'
import { NavLink, Outlet, Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useLogout, useMe } from '@/hooks/useAuth'

const NAV_ITEMS: Array<{ to: string; label: string; icon: typeof FolderKanban; disabled?: boolean }> = [
  { to: '/projects', label: '项目', icon: FolderKanban },
  { to: '/inbox', label: '收集箱', icon: Inbox, disabled: true },
  { to: '/search', label: '搜索', icon: Search, disabled: true },
] as const

export function AppShell() {
  const me = useMe()
  const logout = useLogout()
  const navigate = useNavigate()
  async function handleLogout() {
    try { await logout.mutateAsync(); navigate('/login', { replace: true }); toast.success('已退出登录') }
    catch { toast.error('退出失败，请重试') }
  }
  return <div className="min-h-screen bg-background text-foreground"><div className="mx-auto flex min-h-screen max-w-[1600px] border-x"><aside className="flex w-60 shrink-0 flex-col border-r bg-muted/20"><Link to="/projects" className="flex h-16 items-center gap-2 border-b px-5 font-semibold"><span className="flex size-7 items-center justify-center rounded-md bg-foreground text-background"><Sparkles className="size-4" /></span>知林 Grove</Link><nav className="flex-1 space-y-1 p-3" aria-label="全局导航">{NAV_ITEMS.map(({ to, label, icon: Icon, disabled }) => disabled ? <div key={to} className="flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-2 text-body-sm text-muted-foreground/50" aria-disabled="true"><Icon className="size-4" />{label}<span className="ml-auto text-caption">后续</span></div> : <NavLink key={to} to={to} className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-body-sm ${isActive ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'}`}><Icon className="size-4" />{label}</NavLink>)}<div className="my-4 border-t" /><p className="px-3 text-caption font-medium uppercase tracking-[0.14em] text-muted-foreground">最近项目</p></nav><div className="border-t p-4"><p className="truncate text-body-sm font-medium">{me.data?.user.username ?? '当前账户'}</p><p className="mt-1 truncate text-caption text-muted-foreground">{me.data?.workspace.name ?? 'Workspace'}</p><Button className="mt-3 w-full justify-start" variant="ghost" size="sm" onClick={handleLogout} disabled={logout.isPending}><LogOut className="mr-2 size-4" />{logout.isPending ? '退出中…' : '退出登录'}</Button></div></aside><main className="min-w-0 flex-1"><header className="flex h-16 items-center justify-end border-b px-8"><Button variant="ghost" size="sm" disabled><Settings2 className="mr-2 size-4" />账户设置</Button></header><div className="px-8 py-8"><Outlet /></div></main></div></div>
}
