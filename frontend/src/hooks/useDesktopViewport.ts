import { useSyncExternalStore } from 'react'

function subscribe(onChange: () => void) {
  window.addEventListener('resize', onChange)
  return () => window.removeEventListener('resize', onChange)
}

/** 公开介绍和工作台共用同一桌面边界，避免缩放时认证表单残留。 */
export function useDesktopViewport() {
  return useSyncExternalStore(
    subscribe,
    () => window.innerWidth >= 1024,
    () => true,
  )
}
