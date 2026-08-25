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
    empty.textContent = '还没有截图，按 ⌘S / Ctrl+S 开始'
    batchList.appendChild(empty)
  }
  for (const image of images) {
    const item = document.createElement('div')
    item.className = 'batch-item'
    const img = document.createElement('img')
    img.alt = `批次图片 ${image.id}`
    void getImageBlob(image.id).then((blob) => {
      img.src = URL.createObjectURL(blob)
    })
    const remove = document.createElement('button')
    remove.type = 'button'
    remove.textContent = '✕'
    remove.title = '从批次移除'
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

void refresh()
