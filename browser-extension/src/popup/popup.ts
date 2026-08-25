/** 扩展弹窗：批次管理、发送与服务器设置。 */

import { clearBatch, getBatchImages, getImageBlob, removeBatchImage } from '../lib/batch-db'
import { checkLogin, sendSource } from '../lib/grove'
import { getBaseUrl, setBaseUrl } from '../lib/settings'

const loginStatus = document.querySelector<HTMLElement>('#login-status')!
const batchList = document.querySelector<HTMLElement>('#batch-list')!
const sendBtn = document.querySelector<HTMLButtonElement>('#send-btn')!
const clearBtn = document.querySelector<HTMLButtonElement>('#clear-btn')!
const resultEl = document.querySelector<HTMLElement>('#result')!
const baseUrlInput = document.querySelector<HTMLInputElement>('#base-url')!
const saveBtn = document.querySelector<HTMLButtonElement>('#save-btn')!
const openGroveBtn = document.querySelector<HTMLButtonElement>('#open-grove-btn')!
const captureBtn = document.querySelector<HTMLButtonElement>('#capture-btn')!

let currentBaseUrl = ''

async function refresh(): Promise<void> {
  currentBaseUrl = await getBaseUrl()
  baseUrlInput.value = currentBaseUrl

  const loggedIn = await checkLogin(currentBaseUrl)
  loginStatus.textContent = loggedIn ? '已登录' : '未登录'
  loginStatus.className = `status ${loggedIn ? 'ok' : 'bad'}`

  const images = await getBatchImages()
  batchList.innerHTML = ''
  if (images.length === 0) {
    const empty = document.createElement('p')
    empty.className = 'empty'
    empty.textContent = '还没有截图，按 ⌘⇧S / Ctrl+Shift+S 开始'
    batchList.appendChild(empty)
  }
  for (const image of images) {
    const item = document.createElement('div')
    item.className = 'batch-item'
    const img = document.createElement('img')
    img.alt = `批次图片 ${image.id}`
    void getImageBlob(image.id).then((blob) => {
      img.src = URL.createObjectURL(blob)
    }).catch(() => item.remove())
    const remove = document.createElement('button')
    remove.type = 'button'
    remove.title = '从批次移除'
    remove.innerHTML =
      '<svg viewBox="0 0 24 24" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>'
    remove.addEventListener('click', () => {
      void removeBatchImage(image.id).then(refresh)
    })
    item.appendChild(img)
    item.appendChild(remove)
    batchList.appendChild(item)
  }
  sendBtn.disabled = images.length === 0
}

async function handleSend(): Promise<void> {
  resultEl.textContent = ''
  resultEl.className = 'result'
  const images = await getBatchImages()
  if (images.length === 0) return
  const blobs: Blob[] = []
  for (const image of images) blobs.push(await getImageBlob(image.id))
  const result = await sendSource(currentBaseUrl, blobs)
  if (result.ok) {
    await clearBatch()
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    if (tab?.id) {
      try {
        await chrome.tabs.sendMessage(tab.id, { type: 'BATCH_UPDATED', images: [] })
      } catch {
        // 页面未注入 content script 时忽略
      }
    }
    resultEl.textContent = '已发送到收集箱 ✓'
  } else {
    resultEl.className = 'result error'
    resultEl.textContent = result.message
  }
  await refresh()
}

sendBtn.addEventListener('click', () => {
  void handleSend()
})

clearBtn.addEventListener('click', () => {
  void clearBatch().then(refresh)
})

saveBtn.addEventListener('click', async () => {
  const value = baseUrlInput.value.trim() || 'http://localhost:5173'
  await setBaseUrl(value)
  resultEl.textContent = '已保存'
  await refresh()
})

openGroveBtn.addEventListener('click', () => {
  void chrome.tabs.create({ url: currentBaseUrl })
})

captureBtn.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id) return
  try {
    await chrome.tabs.sendMessage(tab.id, { type: 'START_CAPTURE' })
    window.close()
  } catch {
    // 页面尚未注入 content script（如内置页或旧页面），提示重新加载页面
    resultEl.className = 'result error'
    resultEl.textContent = '当前页面无法截图，请刷新页面后重试（浏览器内置页不支持）'
  }
})

void refresh()
