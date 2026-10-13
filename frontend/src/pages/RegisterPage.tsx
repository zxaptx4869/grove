import { AuthPage } from '@/pages/AuthPage'

/** 保留注册页组件入口，共用产品介绍和认证卡片。 */
export function RegisterPage() {
  return <AuthPage defaultMode="register" />
}
