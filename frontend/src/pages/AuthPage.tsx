import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { AuthPanel } from '@/components/auth/AuthPanel'
import { ProductIntroduction } from '@/components/introduction/ProductIntroduction'
import { useDesktopViewport } from '@/hooks/useDesktopViewport'
import './product-introduction.css'

/** 两条认证路由共用同一页面，切换模式时保留产品介绍。 */
export function AuthPage({ defaultMode = 'login' }: { defaultMode?: 'login' | 'register' }) {
  const desktop = useDesktopViewport()
  const { pathname } = useLocation()
  const path = pathname.replace(/\/+$/, '')
  const mode = path === '/register' ? 'register' : path === '/login' ? 'login' : defaultMode

  useEffect(() => {
    const previous = document.title
    document.title = '知林 Grove · AI 知识共创工具'
    return () => {
      document.title = previous
    }
  }, [])

  return <ProductIntroduction authentication={desktop ? <AuthPanel mode={mode} /> : null} />
}
