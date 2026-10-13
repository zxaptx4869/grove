import { useIsMutating } from '@tanstack/react-query'
import { Tabs } from 'radix-ui'
import { useNavigate } from 'react-router-dom'
import { LoginForm } from '@/components/auth/LoginForm'
import { RegisterForm } from '@/components/auth/RegisterForm'

/** URL 驱动认证标签；提交期间禁止切换，避免交错提交。 */
export function AuthPanel({ mode }: { mode: 'login' | 'register' }) {
  const navigate = useNavigate()
  const pending = useIsMutating({ mutationKey: ['auth', 'access'] }) > 0

  return (
    <section className="intro-auth-panel">
      <h2>欢迎来到 Grove</h2>
      <Tabs.Root
        value={mode}
        activationMode="manual"
        onValueChange={(value) => {
          if (!pending && value !== mode)
            navigate(value === 'register' ? '/register' : '/login', { preventScrollReset: true })
        }}
      >
        <Tabs.List className="intro-auth-selector" aria-label="登录或注册">
          <Tabs.Trigger value="login" disabled={pending}>
            登录
          </Tabs.Trigger>
          <Tabs.Trigger value="register" disabled={pending}>
            注册
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value={mode} className="intro-auth-content">
          {mode === 'login' ? <LoginForm /> : <RegisterForm />}
        </Tabs.Content>
      </Tabs.Root>
    </section>
  )
}
