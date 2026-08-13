import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ChevronDown,
  FolderKanban,
  FolderTree,
  House,
  Inbox,
  LogOut,
  Search,
  UserRound,
} from 'lucide-react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useLogout, useMe } from '@/hooks/useAuth'
import { fetchProjects, type ProjectPayload, type ProjectStatus } from '@/lib/api'

const PROJECT_STATUSES: ProjectStatus[] = ['active', 'paused', 'completed', 'archived']

function useAllProjects() {
  return useQuery({
    queryKey: ['projects', 'all-statuses'],
    queryFn: async () => {
      const groups = await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))
      return groups.flat()
    },
    staleTime: 30_000,
  })
}

function GlobalNavigation({ projects }: { projects: ProjectPayload[] }) {
  const recentProjects = useMemo(
    () => projects.filter((project) => project.status !== 'archived').slice(0, 5),
    [projects],
  )

  return (
    <>
      <nav className="px-2 py-3" aria-label="全局导航">
        <NavLink
          to="/projects"
          className={({ isActive }) => `flex min-h-[38px] items-center gap-[9px] rounded-md px-2.5 text-body ${isActive ? 'bg-brand-soft font-semibold text-brand' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
        >
          <FolderKanban className="size-4" />项目
        </NavLink>
        <div className="flex min-h-[38px] cursor-not-allowed items-center gap-[9px] rounded-md px-2.5 text-body text-muted-foreground/45" aria-disabled="true">
          <Inbox className="size-4" />收集箱
        </div>
        <div className="flex min-h-[38px] cursor-not-allowed items-center gap-[9px] rounded-md px-2.5 text-body text-muted-foreground/45" aria-disabled="true">
          <Search className="size-4" />搜索
        </div>
      </nav>
      <div className="min-h-0 flex-1 px-2 pb-3">
        <p className="px-2.5 pb-1.5 pt-[18px] text-[11px] text-muted-foreground">最近项目</p>
        {recentProjects.length > 0 ? recentProjects.map((project) => (
          <Link key={project.id} to={`/projects/${project.id}`} className="flex min-h-[38px] items-center gap-[9px] rounded-md px-2.5 text-body text-muted-foreground hover:bg-muted hover:text-foreground">
            <FolderTree className="size-4" />
            <span className="truncate">{project.name}</span>
          </Link>
        )) : (
          <p className="px-2 py-2 text-caption text-muted-foreground/70">还没有项目</p>
        )}
      </div>
    </>
  )
}

function ProjectNavigation({ project }: { project?: ProjectPayload }) {
  const location = useLocation()
  const projectId = project?.id ?? Number(location.pathname.match(/^\/projects\/(\d+)/)?.[1])
  const isDirectory = new URLSearchParams(location.search).get('view') === 'directory'
  const statusLabel: Record<ProjectStatus, string> = {
    active: '进行中',
    paused: '暂停',
    completed: '已完成',
    archived: '已归档',
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col px-2 pb-3 pt-2">
      <Link to="/projects" className="mb-2 flex min-h-[34px] items-center gap-2 rounded-md px-2.5 text-caption text-muted-foreground hover:bg-muted hover:text-foreground">
        <ArrowLeft className="size-3.5" />返回全部项目
      </Link>
      <div className="mb-3 px-2.5 pb-1">
        <p className="truncate text-[15px] font-[650] leading-6">{project?.name ?? '项目工作台'}</p>
        <p className="mt-0.5 text-caption text-muted-foreground">{project ? statusLabel[project.status] : '加载中'}</p>
      </div>
      <nav aria-label="项目导航">
        <Link
          to={`/projects/${projectId}`}
          aria-current={!isDirectory ? 'page' : undefined}
          className={`flex min-h-[38px] items-center gap-[9px] rounded-md px-2.5 text-body ${!isDirectory ? 'bg-brand-soft font-semibold text-brand' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
        >
          <House className="size-4" />项目首页
        </Link>
        <Link
          to={`/projects/${projectId}?view=directory`}
          aria-current={isDirectory ? 'page' : undefined}
          className={`flex min-h-[38px] items-center gap-[9px] rounded-md px-2.5 text-body ${isDirectory ? 'bg-brand-soft font-semibold text-brand' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
        >
          <FolderTree className="size-4" />知识空间
        </Link>
      </nav>
    </div>
  )
}

export function AppShell() {
  const me = useMe()
  const projects = useAllProjects()
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()
  const [logoutOpen, setLogoutOpen] = useState(false)
  const projectId = Number(location.pathname.match(/^\/projects\/(\d+)/)?.[1]) || null
  const currentProject = projects.data?.find((project) => project.id === projectId)

  async function handleLogout() {
    try {
      await logout.mutateAsync()
      navigate('/login', { replace: true })
      toast.success('已退出登录')
    } catch {
      toast.error('退出失败，请重试')
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="grid min-h-screen grid-cols-[216px_minmax(0,1fr)] max-[1119px]:grid-cols-[184px_minmax(0,1fr)]">
        <aside className="flex min-h-screen min-w-0 flex-col border-r bg-sidebar">
          <Link to="/projects" className="flex h-[52px] shrink-0 items-center gap-2.5 border-b px-4 text-body font-[650]" aria-label="知林 Grove 项目">
            <span className="flex size-7 items-center justify-center rounded-md bg-brand text-[13px] font-bold text-white" aria-hidden="true">G</span>
            <span>知林 Grove</span>
          </Link>

          {projectId ? <ProjectNavigation project={currentProject} /> : <GlobalNavigation projects={projects.data ?? []} />}

          <div className="border-t px-2 pb-2 pt-1.5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="h-11 w-full justify-start gap-2 px-2 font-normal">
                  <span className="flex size-7 items-center justify-center rounded-md border bg-white"><UserRound className="size-4" /></span>
                  <span className="min-w-0 flex-1 text-left">
                    <span className="block truncate text-body-sm font-medium">{me.data?.user.username ?? '当前账户'}</span>
                    <span className="block truncate text-caption text-muted-foreground">{me.data?.workspace.name ?? 'Workspace'}</span>
                  </span>
                  <ChevronDown className="size-3.5 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" side="top" className="w-[200px]">
                <DropdownMenuLabel>{me.data?.workspace.name ?? '当前 Workspace'}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setLogoutOpen(true)}><LogOut />退出登录</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </aside>
        <main className="flex min-w-0 flex-col bg-background">
          <div className="h-[52px] shrink-0 border-b bg-card" aria-hidden="true" />
          <div className="min-h-0 flex-1"><Outlet /></div>
        </main>
      </div>

      <Dialog open={logoutOpen} onOpenChange={setLogoutOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>退出登录？</DialogTitle>
            <DialogDescription>退出后需要重新输入账号密码才能访问当前 Workspace。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogoutOpen(false)}>取消</Button>
            <Button onClick={handleLogout} disabled={logout.isPending}>{logout.isPending ? '退出中…' : '确认退出'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
