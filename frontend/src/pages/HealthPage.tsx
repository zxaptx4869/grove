import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { fetchHealth } from '@/lib/api'

/** 健康检查页：通过 TanStack Query 调用后端 /healthz。 */
export function HealthPage() {
  const query = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: false,
  })

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">健康检查</h1>
      {query.isLoading && <p className="text-muted-foreground">正在检查后端状态…</p>}
      {query.isError && <p className="text-destructive">后端不可用：{query.error.message}</p>}
      {query.data && (
        <p>
          后端状态：
          <span className="font-medium text-primary">{query.data.status}</span>
          {query.data.version ? `（版本 ${query.data.version}）` : null}
        </p>
      )}
      <Button asChild variant="outline">
        <Link to="/">返回首页</Link>
      </Button>
    </section>
  )
}
