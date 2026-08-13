import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { SourceCapture } from '@/components/features/SourceCapture'

interface ProjectOption {
  id: number
  name: string
}

interface CaptureDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projects: ProjectOption[]
  fixedProjectId?: number
  onCreated: () => void
}

/** 采集弹窗：供项目内「采集到项目」入口使用。 */
export function CaptureDialog({
  open,
  onOpenChange,
  projects,
  fixedProjectId,
  onCreated,
}: CaptureDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>采集到项目</DialogTitle>
        </DialogHeader>
        <SourceCapture
          projects={projects}
          fixedProjectId={fixedProjectId}
          onCreated={() => {
            onCreated()
            onOpenChange(false)
          }}
        />
      </DialogContent>
    </Dialog>
  )
}
