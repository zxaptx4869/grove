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

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'START_CAPTURE') startCapture()
  else if (message.type === 'BATCH_UPDATED') renderBar(message.images as BatchThumb[])
  else if (message.type === 'CAPTURE_DONE') showToast(message.message as string, message.ok === true)
})

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
    showToast('正在处理截图…', true)
    void chrome.runtime.sendMessage({
      type: 'SELECTION_COMPLETE',
      rect: { x, y, width, height } satisfies SelectionRect,
      dpr: window.devicePixelRatio,
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
  if (!bar) {
    bar = document.createElement('div')
    bar.className = 'gv-bar'
    document.documentElement.appendChild(bar)
  }
  bar.innerHTML = ''
  const label = document.createElement('span')
  label.className = 'gv-bar-label'
  label.textContent = `Grove 快采 · ${images.length} 张`
  bar.appendChild(label)

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
    remove.textContent = '✕'
    remove.addEventListener('click', () => {
      void chrome.runtime.sendMessage({ type: 'REMOVE_IMAGE', id: image.id })
    })
    item.appendChild(img)
    item.appendChild(remove)
    list.appendChild(item)
  }
  bar.appendChild(list)

  const send = document.createElement('button')
  send.type = 'button'
  send.className = 'gv-bar-send'
  send.textContent = '发送到收集箱'
  send.disabled = images.length === 0
  send.addEventListener('click', () => {
    void chrome.runtime.sendMessage({ type: 'SEND_BATCH' })
  })
  bar.appendChild(send)
}

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
