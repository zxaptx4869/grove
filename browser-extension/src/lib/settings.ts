/** Grove 服务器地址配置（chrome.storage.local 持久化）。 */

export const DEFAULT_BASE_URL = 'http://localhost:5173'
const KEY = 'groveBaseUrl'

export async function getBaseUrl(): Promise<string> {
  const data = await chrome.storage.local.get(KEY)
  const value = data[KEY] as string | undefined
  return (value || DEFAULT_BASE_URL).replace(/\/+$/, '')
}

export async function setBaseUrl(url: string): Promise<void> {
  await chrome.storage.local.set({ [KEY]: url.trim().replace(/\/+$/, '') })
}
