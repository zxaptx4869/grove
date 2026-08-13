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
import { useRegister } from '@/hooks/useAuth'

const registerSchema = z
  .object({
    username: z
      .string()
      .min(2, '账号至少 2 个字符')
      .max(64, '账号最多 64 个字符')
      .regex(/^\w+$/, '账号只能包含字母、数字与下划线'),
    password: z.string().min(8, '密码至少 8 位').max(128, '密码最多 128 位'),
    confirmPassword: z.string().min(1, '请再次输入密码'),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: '两次输入的密码不一致',
    path: ['confirmPassword'],
  })

type RegisterFormValues = z.infer<typeof registerSchema>

/** 注册页：账号 + 密码（注册即登录）。 */
export function RegisterPage() {
  const navigate = useNavigate()
  const register = useRegister()
  const [submitError, setSubmitError] = useState('')
  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { username: '', password: '', confirmPassword: '' },
  })

  async function onSubmit(values: RegisterFormValues) {
    setSubmitError('')
    try {
      await register.mutateAsync({
        username: values.username,
        password: values.password,
      })
      toast.success('注册成功，已自动登录')
      navigate('/', { replace: true })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : '注册失败，请重试')
    }
  }

  return (
    <section className="w-full space-y-7">
      <div className="space-y-1.5">
        <h1 className="text-display font-semibold">创建账号</h1>
        <p className="text-body-sm text-muted-foreground">注册后会自动创建并进入你的 Workspace。</p>
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
                  <Input className="h-10" placeholder="字母、数字或下划线" autoComplete="username" {...field} />
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
                    placeholder="至少 8 位"
                    autoComplete="new-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="confirmPassword"
            render={({ field }) => (
              <FormItem>
                <FormLabel>确认密码</FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    className="h-10"
                    placeholder="再次输入密码"
                    autoComplete="new-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <Button type="submit" className="h-10 w-full" disabled={register.isPending}>
            {register.isPending ? '注册中…' : '注册'}
          </Button>
        </form>
      </Form>

      <p className="text-body-sm text-muted-foreground">
        已有账号？{' '}
        <Link to="/login" className="text-primary underline-offset-4 hover:underline">
          去登录
        </Link>
      </p>
    </section>
  )
}
