/** 内容脚本：框选遮罩、选区交互与批次预览条。 */

interface SelectionRect {
  x: number
  y: number
  width: number
  height: number
}

interface BatchThumb {
  id: number
  thumb: string
}

let overlay: HTMLElement | null = null
let selectionBox: HTMLElement | null = null
let sizeHint: HTMLElement | null = null
let dragStart: { x: number; y: number } | null = null
let capturing = false

/** 安全发送：扩展上下文失效（刷新/更新后旧脚本）时静默返回，不抛错。 */
function safeSend(message: unknown): Promise<unknown> {
  try {
    return chrome.runtime.sendMessage(message)
  } catch {
    return Promise.resolve(undefined)
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'START_CAPTURE') startCapture()
  else if (message.type === 'BATCH_UPDATED') {
    renderBar(message.images as BatchThumb[])
  }
  else if (message.type === 'CAPTURE_DONE') showToast(message.message as string, message.ok === true)
})

// 页面注入时主动拉取当前批次：切到已打开的页面也能恢复小窗
void safeSend({ type: 'GET_BATCH' }).then((response) => {
  const images = (response as { images?: BatchThumb[] } | undefined)?.images
  if (images) renderBar(images)
}).catch(() => undefined)

function startCapture(): void {
  if (overlay) return
  capturing = false
  overlay = document.createElement('div')
  overlay.className = 'gv-overlay'
  selectionBox = document.createElement('div')
  selectionBox.className = 'gv-selection'
  sizeHint = document.createElement('div')
  sizeHint.className = 'gv-size-hint'
  overlay.appendChild(selectionBox)
  overlay.appendChild(sizeHint)

  const onMove = (event: MouseEvent) => {
    if (!dragStart) return
    const x = Math.min(dragStart.x, event.clientX)
    const y = Math.min(dragStart.y, event.clientY)
    const width = Math.abs(event.clientX - dragStart.x)
    const height = Math.abs(event.clientY - dragStart.y)
    updateSelection(x, y, width, height)
  }
  const onUp = (event: MouseEvent) => {
    if (!dragStart) return
    const x = Math.min(dragStart.x, event.clientX)
    const y = Math.min(dragStart.y, event.clientY)
    const width = Math.abs(event.clientX - dragStart.x)
    const height = Math.abs(event.clientY - dragStart.y)
    dragStart = null
    cleanup()
    if (width < 4 || height < 4) return
    capturing = true
    // 强制一次布局，确保遮罩/选区框从画面撤掉后再抓屏
    void document.body.offsetHeight
    // 等两帧让遮罩与选区框从画面消失，避免被截进图
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        void safeSend({
          type: 'CAPTURE_PREVIEW',
          rect: { x, y, width, height } satisfies SelectionRect,
          dpr: window.devicePixelRatio,
        }).then((response) => {
          const result = response as { ok?: boolean; dataUrl?: string; message?: string }
          if (result?.ok && result.dataUrl) showPreview(result.dataUrl, width)
          else {
            showToast(result?.message || '截图处理失败', false)
          }
        }).catch(() => {
          hidePreview()
          showToast('截图处理失败', false)
        })
      })
    })
  }
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') cleanup()
  }

  overlay.addEventListener('mousedown', (event) => {
    dragStart = { x: event.clientX, y: event.clientY }
    updateSelection(event.clientX, event.clientY, 0, 0)
  })
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  window.addEventListener('keydown', onKey)
  overlay.dataset.cleanup = ''
  document.documentElement.appendChild(overlay)

  function cleanup() {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    window.removeEventListener('keydown', onKey)
    overlay?.remove()
    overlay = null
    selectionBox = null
    sizeHint = null
  }
}

function updateSelection(x: number, y: number, width: number, height: number): void {
  if (!selectionBox || !sizeHint) return
  selectionBox.style.left = `${x}px`
  selectionBox.style.top = `${y}px`
  selectionBox.style.width = `${width}px`
  selectionBox.style.height = `${height}px`
  sizeHint.textContent = `${Math.round(width)} × ${Math.round(height)}`
  sizeHint.style.left = `${x + width + 6}px`
  sizeHint.style.top = `${y + 6}px`
}

let bar: HTMLElement | null = null

function renderBar(images: BatchThumb[]): void {
  if (images.length === 0) {
    bar?.remove()
    bar = null
    return
  }
  if (!bar) {
    bar = document.createElement('div')
    bar.className = 'gv-bar'
    bar.dataset.draggable = ''
    document.documentElement.appendChild(bar)
  }
  bar.innerHTML = ''
  const label = document.createElement('span')
  label.className = 'gv-bar-label'
  label.textContent = `Grove · ${images.length} 张`
  bar.appendChild(label)
  bar.appendChild(createCloseButton())

  const list = document.createElement('div')
  list.className = 'gv-bar-list'
  for (const image of images) {
    const item = document.createElement('div')
    item.className = 'gv-bar-item'
    const img = document.createElement('img')
    img.src = image.thumb
    img.alt = `批次图片 ${image.id}`
    const remove = document.createElement('button')
    remove.type = 'button'
    remove.className = 'gv-bar-remove'
    remove.title = '从批次移除'
    remove.innerHTML =
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>'
    remove.addEventListener('click', () => {
      void safeSend({ type: 'REMOVE_IMAGE', id: image.id }).catch(() => undefined)
    })
    item.appendChild(img)
    item.appendChild(remove)
    list.appendChild(item)
  }
  bar.appendChild(list)

  const send = document.createElement('button')
  send.type = 'button'
  send.className = 'gv-bar-send'
  send.textContent = '发送'
  send.disabled = images.length === 0
  send.addEventListener('click', () => {
    void safeSend({ type: 'SEND_BATCH' }).catch(() => undefined)
  })
  bar.appendChild(send)
}

function createCloseButton(): HTMLButtonElement {
  const close = document.createElement('button')
  close.type = 'button'
  close.className = 'gv-bar-close'
  close.title = '关闭并清空批次'
  close.innerHTML =
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>'
  close.addEventListener('click', () => {
    bar?.remove()
    bar = null
    void safeSend({ type: 'CLEAR_BATCH' }).catch(() => undefined)
  })
  return close
}

let preview: HTMLElement | null = null

function showPreview(dataUrl: string, widthPx?: number): void {
  hidePreview()
  preview = document.createElement('div')
  preview.className = 'gv-preview'

  const stage = document.createElement('div')
  stage.className = 'gv-preview-stage'
  const frame = document.createElement('div')
  frame.className = 'gv-preview-frame'
  const img = document.createElement('img')
  img.src = dataUrl
  img.alt = '截图预览'
  // 按框选区域的逻辑尺寸显示（Retina 屏避免被 dpr 放大），大图由 CSS 约束缩放
  if (widthPx && widthPx > 0) {
    img.style.width = `${widthPx}px`
  }
  frame.appendChild(img)

  const closeBtn = document.createElement('button')
  closeBtn.type = 'button'
  closeBtn.className = 'gv-preview-close'
  closeBtn.innerHTML =
    '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>'
  closeBtn.addEventListener('click', () => {
    void safeSend({ type: 'DISCARD_PREVIEW' }).catch(() => undefined)
    hidePreview()
  })
  frame.appendChild(closeBtn)

  const actions = document.createElement('div')
  actions.className = 'gv-preview-actions'
  const stashBtn = document.createElement('button')
  stashBtn.type = 'button'
  stashBtn.className = 'gv-preview-btn'
  stashBtn.textContent = '暂存'
  stashBtn.dataset.tooltip =
    '暂存：收进批次继续截图，最后一起作为一条采集发送。长内容分多张截图时用这个；单张直接点发送。'
  stashBtn.addEventListener('click', () => {
    void safeSend({ type: 'STASH_PREVIEW' }).catch(() => undefined)
    hidePreview()
  })
  const sendBtn = document.createElement('button')
  sendBtn.type = 'button'
  sendBtn.className = 'gv-preview-btn gv-preview-send'
  sendBtn.textContent = '发送'
  sendBtn.addEventListener('click', () => {
    void safeSend({ type: 'SEND_SINGLE' }).then((response) => {
      const result = response as { ok?: boolean; message?: string }
      hidePreview()
      showToast(result?.message || '发送结果未知', result?.ok === true)
    }).catch(() => {
      hidePreview()
      showToast('发送失败', false)
    })
  })
  actions.appendChild(stashBtn)
  actions.appendChild(sendBtn)
  frame.appendChild(actions)
  stage.appendChild(frame)
  stage.appendChild(actions)
  preview.appendChild(stage)
  document.documentElement.appendChild(preview)

  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      void safeSend({ type: 'DISCARD_PREVIEW' }).catch(() => undefined)
      hidePreview()
    }
  }
  window.addEventListener('keydown', onKey)
  preview.dataset.keyHandler = ''
  preview.addEventListener(
    'remove',
    () => window.removeEventListener('keydown', onKey),
    { once: true },
  )
}

function hidePreview(): void {
  preview?.remove()
  preview = null
}

// 拖动小窗：按住非按钮区域可自由移动位置（document 级委托，bar 动态创建/销毁）
let dragState: {
  startX: number
  startY: number
  originLeft: number
  originTop: number
} | null = null

document.addEventListener('mousedown', (event) => {
  if (!bar) return
  if ((event.target as HTMLElement).closest('.gv-bar') !== bar) return
  if ((event.target as HTMLElement).closest('button, img')) return
  dragState = {
    startX: event.clientX,
    startY: event.clientY,
    originLeft: bar.offsetLeft,
    originTop: bar.offsetTop,
  }
  bar.classList.add('gv-bar-dragging')
  event.preventDefault()
})

document.addEventListener('mousemove', (event) => {
  if (!dragState || !bar) return
  const left = Math.max(0, dragState.originLeft + event.clientX - dragState.startX)
  const top = Math.max(0, dragState.originTop + event.clientY - dragState.startY)
  bar.style.left = `${left}px`
  bar.style.top = `${top}px`
  bar.style.right = 'auto'
  bar.style.bottom = 'auto'
})

document.addEventListener('mouseup', () => {
  dragState = null
  bar?.classList.remove('gv-bar-dragging')
})

let toastTimer: number | undefined

function showToast(message: string, success: boolean): void {
  const existing = document.querySelector('.gv-toast')
  existing?.remove()
  const toast = document.createElement('div')
  toast.className = `gv-toast ${success ? 'gv-toast-ok' : 'gv-toast-error'}`
  toast.textContent = message
  document.documentElement.appendChild(toast)
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => toast.remove(), 3500)
}
