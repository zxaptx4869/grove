import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

/** 占位首页：骨架阶段只展示产品定位。 */
export function HomePage() {
  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-bold sm:text-3xl">知林 Grove</h1>
        <p className="text-muted-foreground">
          个人知识管家：把散落在各处的收藏、截图与文档，在人与 AI 的共创下，
          沉淀为属于你自己的结构化知识库。
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link to="/health">查看后端健康状态</Link>
        </Button>
      </div>
    </section>
  )
}
