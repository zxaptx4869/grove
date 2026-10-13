import { useEffect } from 'react'
import { LoginForm } from '@/components/auth/LoginForm'
import { ProductIntroduction } from '@/components/introduction/ProductIntroduction'
import { useDesktopViewport } from '@/hooks/useDesktopViewport'
import './product-introduction.css'

/** 公开介绍和真实登录共享入口，小屏只提供产品阅读。 */
export function LoginPage() {
  const desktop = useDesktopViewport()

  useEffect(() => {
    const previous = document.title
    document.title = '知林 Grove · AI 知识共创工具'
    return () => {
      document.title = previous
    }
  }, [])

  return <ProductIntroduction login={desktop ? <LoginForm /> : null} />
}
