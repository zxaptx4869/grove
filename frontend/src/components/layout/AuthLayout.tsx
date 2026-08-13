import type { ReactNode } from 'react'
import { Sprout } from 'lucide-react'
import { Link } from 'react-router-dom'

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen bg-background">
      <header className="flex h-16 items-center px-8">
        <Link to="/login" className="inline-flex items-center gap-2 text-body-sm font-semibold" aria-label="知林 Grove 登录">
          <span className="flex size-7 items-center justify-center rounded-md bg-brand text-white"><Sprout className="size-4" /></span>
          <span>知林 Grove</span>
        </Link>
      </header>
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-[420px] items-start px-6 pt-[12vh]">
        <div className="w-full">{children}</div>
      </div>
    </main>
  )
}
