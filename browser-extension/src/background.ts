/** Grove 快采后台：快捷键触发框选、截图裁剪、批次管理与发送到收集箱。 */

import {
  addBatchImage,
  clearBatch,
  clearPendingBlob,
  getBatchImages,
  getImageBlob,
  getPendingBlob,
  removeBatchImage,
  savePendingBlob,
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
  void startCapture().catch(() => undefined)
})

chrome.runtime.onMessage.addListener((message: Message, sender, sendResponse) => {
  void handleMessage(message, sender.tab?.id)
    .then(sendResponse)
    .catch((error: unknown) => {
      sendResponse({
        ok: false,
        message: error instanceof Error ? error.message : String(error),
      })
    })
  return true
})

type Message =
  | { type: 'CAPTURE_PREVIEW'; rect: SelectionRect; dpr: number }
  | { type: 'SEND_SINGLE' }
  | { type: 'STASH_PREVIEW' }
  | { type: 'DISCARD_PREVIEW' }
  | { type: 'SEND_BATCH' }
  | { type: 'REMOVE_IMAGE'; id: number }
  | { type: 'CLEAR_BATCH' }
  | { type: 'GET_BATCH' }

async function startCapture(): Promise<void> {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (!tab?.id) return
    const ok = await notifyContent(tab.id, { type: 'START_CAPTURE' })
    if (!ok) {
      // 内置页或扩展受限页面无法注入，弹出提示
      const [active] = await chrome.tabs.query({ active: true, currentWindow: true })
      if (active?.url?.startsWith('chrome://') || active?.url?.startsWith('https://chrome.google.com')) {
        void chrome.action.openPopup?.().catch(() => undefined)
      }
    }
  } catch {
    // 查询或通信失败时静默忽略（例如扩展被禁用瞬间）
  }
}

async function handleMessage(message: Message, tabId: number | undefined): Promise<unknown> {
  switch (message.type) {
    case 'CAPTURE_PREVIEW':
      return handlePreview(message.rect, message.dpr)
    case 'SEND_SINGLE':
      return handleSendSingle()
    case 'STASH_PREVIEW':
      return handleStashPreview()
    case 'DISCARD_PREVIEW':
      await clearPendingBlob()
      return { ok: true }
    case 'SEND_BATCH':
      return handleSendBatch(tabId)
    case 'REMOVE_IMAGE':
      await removeBatchImage(message.id)
      await broadcastBatch()
      return { ok: true }
    case 'CLEAR_BATCH':
      await clearBatch()
      await broadcastBatch()
      return { ok: true }
    case 'GET_BATCH':
      return { images: await buildBatchThumbs() }
  }
}

async function handlePreview(
  rect: SelectionRect,
  dpr: number,
): Promise<{ ok: boolean; message?: string; dataUrl?: string }> {
  try {
    // 兜底等待：确保页面已重绘（遮罩/选区框已从画面消失）
    await new Promise((resolve) => setTimeout(resolve, 30))
    const dataUrl = await chrome.tabs.captureVisibleTab(chrome.windows.WINDOW_ID_CURRENT, {
      format: 'jpeg',
      quality: 92,
    })
    const blob = await cropImage(dataUrl, rect, dpr)
    await savePendingBlob(blob)
    const previewUrl = await makePreviewDataUrl(blob)
    return { ok: true, dataUrl: previewUrl }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  }
}

async function handleSendSingle(): Promise<{
  ok: boolean
  message: string
  notLoggedIn?: boolean
}> {
  const baseUrl = await getBaseUrl()
  const blob = await getPendingBlob()
  if (!blob) return { ok: false, message: '没有待发送的截图' }
  const loggedIn = await checkLogin(baseUrl)
  if (!loggedIn) {
    return { ok: false, notLoggedIn: true, message: '请先登录 Grove 再发送' }
  }
  const result = await sendSource(baseUrl, [blob])
  await clearPendingBlob()
  return result
}

async function handleStashPreview(): Promise<{ ok: boolean; message?: string }> {
  const blob = await getPendingBlob()
  if (!blob) return { ok: false, message: '没有可暂存的截图' }
  await addBatchImage(blob)
  await clearPendingBlob()
  await broadcastBatch()
  return { ok: true }
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
  if (result.ok) {
    await clearBatch()
    await broadcastBatch()
  }
  await notifyContent(tabId, {
    type: 'CAPTURE_DONE',
    ok: result.ok,
    message: result.message,
  })
  return result
}

async function broadcastBatch(): Promise<void> {
  const thumbs = await buildBatchThumbs()
  // 广播到所有标签页，保证切换标签后小窗状态一致
  const tabs = await chrome.tabs.query({})
  for (const tab of tabs) {
    if (tab.id != null) {
      await notifyContent(tab.id, { type: 'BATCH_UPDATED', images: thumbs })
    }
  }
}

async function buildBatchThumbs(): Promise<BatchThumb[]> {
  const images = await getBatchImages()
  const thumbs: BatchThumb[] = []
  for (const image of images) {
    const blob = await getImageBlob(image.id)
    thumbs.push({ id: image.id, thumb: await makeThumb(blob) })
  }
  return thumbs
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

async function makePreviewDataUrl(blob: Blob): Promise<string> {
  const bitmap = await createImageBitmap(blob)
  const scale = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height))
  const width = Math.max(1, Math.round(bitmap.width * scale))
  const height = Math.max(1, Math.round(bitmap.height * scale))
  const canvas = new OffscreenCanvas(width, height)
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''
  ctx.drawImage(bitmap, 0, 0, width, height)
  return blobToDataUrl(await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.8 }))
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
