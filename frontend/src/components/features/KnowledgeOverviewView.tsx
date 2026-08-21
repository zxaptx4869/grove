import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Columns3 } from 'lucide-react'

import { MindMapView } from '@/components/features/MindMapView'
import { SunburstPanel } from '@/components/features/SunburstPanel'
import { Button } from '@/components/ui/button'

type OverviewMode = 'sunburst' | 'mindmap'

/** 知识全景视图：默认旭日图，顶部切换旭日图 / 思维导图，两模式保持挂载以保留状态。 */
export function KnowledgeOverviewView({
  projectId,
  projectName,
}: {
  projectId: number
  projectName: string
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawMode = searchParams.get('mode')
  const mode: OverviewMode = rawMode === 'mindmap' ? 'mindmap' : 'sunburst'
  const nodeParam = searchParams.get('node')
  const initialNodeId =
    nodeParam != null && Number.isFinite(Number(nodeParam)) ? Number(nodeParam) : null
  const [sideOpen, setSideOpen] = useState(true)

  function switchMode(next: OverviewMode) {
    setSearchParams(
      { view: 'overview', mode: next, ...(nodeParam ? { node: nodeParam } : {}) },
      { replace: true },
    )
  }

  function openInMindMap(nodeId: number) {
    setSearchParams(
      { view: 'overview', mode: 'mindmap', node: String(nodeId) },
      { replace: true },
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Button asChild size="sm" variant="ghost">
            <Link to={`/projects/${projectId}?view=directory`}>
              <ArrowLeft />
              返回知识空间
            </Link>
          </Button>
          <h1 className="truncate text-body font-[650]">{projectName} · 知识全景</h1>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="flex items-center rounded-md border" role="group" aria-label="模式切换">
            <button
              type="button"
              onClick={() => switchMode('sunburst')}
              aria-pressed={mode === 'sunburst'}
              className={`flex h-8 items-center px-3 text-body-sm ${
                mode === 'sunburst'
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              旭日图
            </button>
            <button
              type="button"
              onClick={() => switchMode('mindmap')}
              aria-pressed={mode === 'mindmap'}
              className={`flex h-8 items-center px-3 text-body-sm ${
                mode === 'mindmap'
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              思维导图
            </button>
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => setSideOpen((open) => !open)}
            aria-label={sideOpen ? '收起侧栏' : '展开侧栏'}
            title={sideOpen ? '收起侧栏' : '展开侧栏'}
          >
            <Columns3 className="size-4" />
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <div className={mode === 'sunburst' ? 'h-full' : 'hidden'}>
          <SunburstPanel
            key={`sunburst-${initialNodeId ?? 'root'}`}
            projectId={projectId}
            projectName={projectName}
            initialNodeId={initialNodeId}
            sideOpen={sideOpen}
            onOpenInMindMap={openInMindMap}
          />
        </div>
        <div className={mode === 'mindmap' ? 'h-full' : 'hidden'}>
          <MindMapView
            key={`mindmap-${initialNodeId ?? 'root'}`}
            projectId={projectId}
            projectName={projectName}
            embedded
            sideOpen={sideOpen}
            onToggleSide={() => setSideOpen((open) => !open)}
          />
        </div>
      </div>
    </div>
  )
}
