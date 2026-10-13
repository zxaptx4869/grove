import { useIsMutating } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { LoginForm } from '@/components/auth/LoginForm'
import { RegisterForm } from '@/components/auth/RegisterForm'

/** 保留原表单样式，通过底部链接在同一卡片切换认证模式。 */
export function AuthPanel({ mode }: { mode: 'login' | 'register' }) {
  const pending = useIsMutating({ mutationKey: ['auth', 'access'] }) > 0
  const login = mode === 'login'

  return (
    <section className="intro-auth-panel space-y-6" aria-labelledby="intro-auth-title">
      <div className="space-y-1">
        <h2 id="intro-auth-title">{login ? '登录' : '创建账号'}</h2>
        <p className="text-body text-muted-foreground">
          {login ? '进入你的知识工作台。' : '注册后自动登录，开始整理知识。'}
        </p>
      </div>
      {login ? <LoginForm /> : <RegisterForm />}
      <p className="text-body-sm text-muted-foreground">
        {login ? '没有账号？' : '已有账号？'}{' '}
        <Link
          to={login ? '/register' : '/login'}
          preventScrollReset
          className="intro-auth-switch text-primary underline-offset-4 hover:underline"
          aria-disabled={pending || undefined}
          tabIndex={pending ? -1 : undefined}
          onClick={(event) => {
            if (pending) event.preventDefault()
          }}
        >
          {login ? '去注册' : '去登录'}
        </Link>
      </p>
    </section>
  )
}
