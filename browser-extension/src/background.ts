/** Grove 快采后台：快捷键触发框选、截图裁剪、批次管理与发送到收集箱。 */

import {
  addBatchImage,
  clearBatch,
  getBatchImages,
  getImageBlob,
  removeBatchImage,
} from './lib/batch-db'
import { checkLogin, sendSource } from './lib/grove'
import { getBaseUrl } from './lib/settings'

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

chrome.commands.onCommand.addListener((command) => {
  if (command !== 'capture') return
  void startCapture()
})

chrome.runtime.onMessage.addListener((message: Message, sender, sendResponse) => {
  void handleMessage(message, sender.tab?.id).then(sendResponse)
  return true
})

type Message =
  | { type: 'SELECTION_COMPLETE'; rect: SelectionRect; dpr: number }
  | { type: 'SEND_BATCH' }
  | { type: 'REMOVE_IMAGE'; id: number }
  | { type: 'CLEAR_BATCH' }

async function startCapture(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id) return
  const ok = await notifyContent(tab.id, { type: 'START_CAPTURE' })
  if (!ok) {
    // 内置页或扩展受限页面无法注入，弹出提示
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (active?.url?.startsWith('chrome://') || active?.url?.startsWith('https://chrome.google.com')) {
      void chrome.action.openPopup?.()
    }
  }
}

async function handleMessage(message: Message, tabId: number | undefined): Promise<unknown> {
  switch (message.type) {
    case 'SELECTION_COMPLETE':
      return handleSelection(message.rect, message.dpr, tabId)
    case 'SEND_BATCH':
      return handleSendBatch(tabId)
    case 'REMOVE_IMAGE':
      await removeBatchImage(message.id)
      await broadcastBatch(tabId)
      return { ok: true }
    case 'CLEAR_BATCH':
      await clearBatch()
      await broadcastBatch(tabId)
      return { ok: true }
  }
}

async function handleSelection(
  rect: SelectionRect,
  dpr: number,
  tabId: number | undefined,
): Promise<{ ok: boolean; message?: string }> {
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(chrome.windows.WINDOW_ID_CURRENT, {
      format: 'png',
    })
    const blob = await cropImage(dataUrl, rect, dpr)
    await addBatchImage(blob)
    await broadcastBatch(tabId)
    return { ok: true }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  }
}

async function cropImage(
  dataUrl: string,
  rect: SelectionRect,
  dpr: number,
): Promise<Blob> {
  const source = await createImageBitmap(await (await fetch(dataUrl)).blob())
  const width = Math.max(1, Math.round(rect.width * dpr))
  const height = Math.max(1, Math.round(rect.height * dpr))
  const canvas = new OffscreenCanvas(width, height)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法创建画布')
  ctx.drawImage(
    source,
    rect.x * dpr,
    rect.y * dpr,
    rect.width * dpr,
    rect.height * dpr,
    0,
    0,
    width,
    height,
  )
  return canvas.convertToBlob({ type: 'image/png' })
}

async function handleSendBatch(
  tabId: number | undefined,
): Promise<{ ok: boolean; message: string; notLoggedIn?: boolean }> {
  const baseUrl = await getBaseUrl()
  const images = await getBatchImages()
  if (images.length === 0) {
    return { ok: false, message: '批次为空，先截图再加入' }
  }
  const loggedIn = await checkLogin(baseUrl)
  if (!loggedIn) {
    const result = { ok: false, notLoggedIn: true, message: '请先登录 Grove 再发送' }
    await notifyContent(tabId, { type: 'CAPTURE_DONE', ...result })
    return result
  }
  const blobs: Blob[] = []
  for (const image of images) {
    blobs.push(await getImageBlob(image.id))
  }
  const result = await sendSource(baseUrl, blobs)
  if (result.ok) await clearBatch()
  await notifyContent(tabId, {
    type: 'CAPTURE_DONE',
    ok: result.ok,
    message: result.message,
  })
  return result
}

async function broadcastBatch(tabId: number | undefined): Promise<void> {
  if (tabId == null) return
  const images = await getBatchImages()
  const thumbs: BatchThumb[] = []
  for (const image of images) {
    const blob = await getImageBlob(image.id)
    thumbs.push({ id: image.id, thumb: await makeThumb(blob) })
  }
  await notifyContent(tabId, { type: 'BATCH_UPDATED', images: thumbs })
}

async function makeThumb(blob: Blob): Promise<string> {
  const bitmap = await createImageBitmap(blob)
  const width = 96
  const height = Math.max(1, Math.round((bitmap.height * width) / bitmap.width))
  const canvas = new OffscreenCanvas(width, height)
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  ctx.drawImage(bitmap, 0, 0, width, height)
  return blobToDataUrl(await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.7 }))
}

async function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(blob)
  })
}

async function notifyContent(tabId: number | undefined, message: unknown): Promise<boolean> {
  if (tabId == null) return false
  try {
    await chrome.tabs.sendMessage(tabId, message)
    return true
  } catch {
    return false
  }
}
