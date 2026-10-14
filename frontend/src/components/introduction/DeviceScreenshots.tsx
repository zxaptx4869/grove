import { useLayoutEffect, useRef, useState } from 'react'
import { Tabs } from 'radix-ui'
import { ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import extensionCapture from '@/assets/introduction/extension-capture.png'
import extensionPanel from '@/assets/introduction/extension-panel.png'
import mobileAgent from '@/assets/introduction/mobile-agent-clean.png'
import mobileInbox from '@/assets/introduction/mobile-inbox-clean.png'
import webAgent from '@/assets/introduction/web-agent.jpg'
import webInbox from '@/assets/introduction/web-inbox.png'
import webReview from '@/assets/introduction/web-review.png'

type Screenshot = {
  title: string
  src: string
  alt: string
  width: number
  height: number
}

const extensionScreenshots: Screenshot[] = [
  {
    title: '快采面板',
    src: extensionPanel,
    alt: 'Grove 快采扩展提供截图快捷键、批次暂存与发送到收集箱。',
    width: 648,
    height: 996,
  },
  {
    title: '框选采集',
    src: extensionCapture,
    alt: '扩展框选装修经验后预览截图，可暂存或发送到 Grove。',
    width: 1030,
    height: 692,
  },
]
const mobileScreenshots: Screenshot[] = [
  {
    title: '知识对话',
    src: mobileAgent,
    alt: 'App 知识 Agent 对话，介绍查找、理解、比较知识及整理候选的能力。',
    width: 862,
    height: 1824,
  },
  {
    title: '随手收集',
    src: mobileInbox,
    alt: 'App 收集箱提供相机、相册、文本入口，展示材料的处理与确认状态。',
    width: 860,
    height: 1828,
  },
]
const webScreenshots: Screenshot[] = [
  {
    title: '知识 Agent',
    src: webAgent,
    alt: 'Web 知识 Agent 从星露谷攻略中找到相关正式记录，并展示记录正文。',
    width: 1710,
    height: 836,
  },
  {
    title: '收集箱',
    src: webInbox,
    alt: 'Web 收集箱支持批量放入截图或粘贴文字，集中查看来源与处理状态。',
    width: 3420,
    height: 1788,
  },
  {
    title: '确认台',
    src: webReview,
    alt: 'Web 确认台并排展示原始材料、证据与 AI 推荐候选，等待人工审阅采纳。',
    width: 3420,
    height: 1786,
  },
]

/** 以适应视口的大小为基准缩放，放大后保留真实滚动区域。 */
function ScreenshotViewer({ screenshot }: { screenshot: Screenshot }) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const [fitScale, setFitScale] = useState(1)
  const [zoom, setZoom] = useState(1)

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const update = () => {
      if (viewport.clientWidth && viewport.clientHeight) {
        setFitScale(
          Math.min(
            1,
            viewport.clientWidth / screenshot.width,
            viewport.clientHeight / screenshot.height,
          ),
        )
      }
    }
    update()
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(update)
      observer.observe(viewport)
      return () => observer.disconnect()
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [screenshot.width, screenshot.height])

  function reset() {
    setZoom(1)
    const viewport = viewportRef.current
    if (viewport) {
      viewport.scrollLeft = 0
      viewport.scrollTop = 0
    }
  }

  return (
    <>
      <div className="intro-screenshot-toolbar" role="group" aria-label="截图缩放">
        <Button
          variant="outline"
          size="icon"
          aria-label="缩小截图"
          disabled={zoom === 1}
          onClick={() => setZoom((value) => Math.max(1, value - 0.5))}
        >
          <ZoomOut />
        </Button>
        <output aria-label="截图缩放比例">{Math.round(zoom * 100)}%</output>
        <Button
          variant="outline"
          size="icon"
          aria-label="放大截图"
          disabled={zoom === 4}
          onClick={() => setZoom((value) => Math.min(4, value + 0.5))}
        >
          <ZoomIn />
        </Button>
        <Button variant="ghost" onClick={reset}>
          适应窗口
        </Button>
      </div>
      <div
        ref={viewportRef}
        className="intro-screenshot-full"
        role="region"
        aria-label="截图查看区域"
        tabIndex={0}
        data-zoomed={zoom > 1}
        onPointerDown={(event) => {
          // 触屏保留原生滑动；鼠标拖动使用滚动位置，不改变图片比例。
          if (event.pointerType !== 'mouse' || event.button !== 0 || zoom === 1) return
          const viewport = event.currentTarget
          dragRef.current = {
            x: event.clientX,
            y: event.clientY,
            left: viewport.scrollLeft,
            top: viewport.scrollTop,
          }
          viewport.setPointerCapture(event.pointerId)
          viewport.dataset.dragging = 'true'
          event.preventDefault()
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          if (!drag) return
          event.currentTarget.scrollLeft = drag.left + drag.x - event.clientX
          event.currentTarget.scrollTop = drag.top + drag.y - event.clientY
        }}
        onLostPointerCapture={(event) => {
          dragRef.current = null
          delete event.currentTarget.dataset.dragging
        }}
        onPointerUp={(event) => {
          if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId)
        }}
        onPointerCancel={(event) => {
          dragRef.current = null
          delete event.currentTarget.dataset.dragging
        }}
      >
        <div className="intro-screenshot-canvas">
          <img
            src={screenshot.src}
            alt={screenshot.alt}
            width={screenshot.width}
            height={screenshot.height}
            draggable={false}
            style={{
              width: screenshot.width * fitScale * zoom,
              height: screenshot.height * fitScale * zoom,
            }}
          />
        </div>
      </div>
    </>
  )
}

function ScreenshotPreview({ screenshot }: { screenshot: Screenshot }) {
  return (
    <figure className="intro-screenshot">
      <Dialog>
        <DialogTrigger asChild>
          <button
            type="button"
            className="intro-screenshot-button"
            aria-label={`放大查看${screenshot.title}截图`}
          >
            <img
              src={screenshot.src}
              alt={screenshot.alt}
              width={screenshot.width}
              height={screenshot.height}
              loading="lazy"
              decoding="async"
            />
            <span className="intro-screenshot-zoom" aria-hidden="true">
              <ZoomIn size={18} />
            </span>
          </button>
        </DialogTrigger>
        <DialogContent className="intro-screenshot-dialog" aria-describedby={undefined}>
          <DialogTitle>{screenshot.title}</DialogTitle>
          <ScreenshotViewer screenshot={screenshot} />
        </DialogContent>
      </Dialog>
      <figcaption>{screenshot.title}</figcaption>
    </figure>
  )
}

export function DeviceScreenshots() {
  return (
    <div className="intro-devices">
      <article className="intro-device-row">
        <div className="intro-device-copy">
          <h3>浏览器扩展</h3>
          <p>浏览网页时框选截图，单张或批量发送到收集箱。</p>
          <small>Chrome / Edge · 本地加载</small>
        </div>
        <div className="intro-extension-gallery">
          {extensionScreenshots.map((screenshot) => (
            <ScreenshotPreview key={screenshot.title} screenshot={screenshot} />
          ))}
        </div>
      </article>
      <article className="intro-device-row">
        <div className="intro-device-copy">
          <h3>移动 App</h3>
          <p>随手拍照、选图或记录文字，也能通过 Agent 查找和理解知识。</p>
          <small>开发体验阶段</small>
        </div>
        <div className="intro-mobile-gallery">
          {mobileScreenshots.map((screenshot) => (
            <ScreenshotPreview key={screenshot.title} screenshot={screenshot} />
          ))}
        </div>
      </article>
      <article className="intro-device-row">
        <div className="intro-device-copy">
          <h3>桌面 Web</h3>
          <p>集中审阅 AI 候选、共创目录，浏览、搜索和维护项目知识。</p>
        </div>
        <Tabs.Root defaultValue="知识 Agent" className="intro-web-gallery">
          <Tabs.List className="intro-screenshot-tabs" aria-label="Web 界面截图">
            {webScreenshots.map((screenshot) => (
              <Tabs.Trigger key={screenshot.title} value={screenshot.title}>
                {screenshot.title}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          {webScreenshots.map((screenshot) => (
            <Tabs.Content
              key={screenshot.title}
              value={screenshot.title}
              className="intro-screenshot-panel"
            >
              <ScreenshotPreview screenshot={screenshot} />
            </Tabs.Content>
          ))}
        </Tabs.Root>
      </article>
    </div>
  )
}
