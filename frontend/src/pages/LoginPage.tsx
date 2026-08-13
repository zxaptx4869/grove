import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { useLogin } from '@/hooks/useAuth'

const loginSchema = z.object({
  username: z.string().min(2, '请输入账号'),
  password: z.string().min(1, '请输入密码'),
})

type LoginFormValues = z.infer<typeof loginSchema>

/** 登录页：账号 + 密码，复用表单基座。 */
export function LoginPage() {
  const navigate = useNavigate()
  const login = useLogin()
  const [submitError, setSubmitError] = useState('')
  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: '', password: '' },
  })

  async function onSubmit(values: LoginFormValues) {
    setSubmitError('')
    try {
      await login.mutateAsync(values)
      toast.success('登录成功')
      navigate('/', { replace: true })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '登录失败，请重试')
    }
  }

  return (
    <section className="w-full space-y-7">
      <div className="space-y-1.5">
        <h1 className="text-display font-semibold">登录</h1>
        <p className="text-body-sm text-muted-foreground">进入你的 Workspace，继续整理项目。</p>
      </div>

      <Form {...form}>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          {submitError ? <div role="alert" className="rounded-md border border-destructive/20 bg-error-soft px-3 py-2 text-body-sm text-destructive">{submitError}</div> : null}
          <FormField
            control={form.control}
            name="username"
            render={({ field }) => (
              <FormItem>
                <FormLabel>账号</FormLabel>
                <FormControl>
                  <Input className="h-10" placeholder="输入账号" autoComplete="username" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>密码</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    className="h-10"
                    placeholder="输入密码"
                    autoComplete="current-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="h-10 w-full" disabled={login.isPending}>
            {login.isPending ? '登录中…' : '登录'}
          </Button>
        </form>
      </Form>

      <p className="text-body-sm text-muted-foreground">
        还没有账号？{' '}
        <Link to="/register" className="text-primary underline-offset-4 hover:underline">
          注册一个
        </Link>
      </p>
    </section>
  )
}
