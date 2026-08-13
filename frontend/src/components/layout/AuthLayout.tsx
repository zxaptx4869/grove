import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen bg-background">
      <header className="flex h-[52px] items-center border-b bg-card px-5">
        <Link to="/login" className="inline-flex items-center gap-2.5 text-body font-[650]" aria-label="知林 Grove 登录">
          <span className="flex size-7 items-center justify-center rounded-md bg-brand text-[13px] font-bold text-white" aria-hidden="true">G</span>
          <span>知林 Grove</span>
        </Link>
      </header>
      <div className="mx-auto flex min-h-[calc(100vh-52px)] w-full max-w-[408px] items-start px-6 pb-10 pt-[88px]">
        <div className="w-full">{children}</div>
      </div>
    </main>
  )
}
