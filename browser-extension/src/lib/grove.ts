/** Grove API 调用：登录校验与多图 Source 上传。 */

export async function checkLogin(baseUrl: string): Promise<boolean> {
  try {
    const response = await fetch(`${baseUrl}/api/me`, {
      credentials: 'include',
    })
    return response.ok
  } catch {
    return false
  }
}

export async function sendSource(
  baseUrl: string,
  blobs: Blob[],
): Promise<{ ok: boolean; status: number; message: string; sourceId?: number }> {
  const form = new FormData()
  blobs.forEach((blob, index) => {
    form.append('files', blob, `capture-${Date.now()}-${index}.png`)
  })
  try {
    const response = await fetch(`${baseUrl}/api/sources`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    })
    if (response.ok) {
      let sourceId: number | undefined
      try {
        const data = (await response.json()) as { id?: number }
        sourceId = data.id
      } catch {
        // 忽略响应解析失败，Source 已创建
      }
      // 与网页端采集一致：创建后立即触发处理
      if (sourceId != null) {
        try {
          await fetch(`${baseUrl}/api/sources/${sourceId}/process`, {
            method: 'POST',
            credentials: 'include',
          })
        } catch {
          // 处理启动失败不阻塞发送结果，Source 保留在等待处理
        }
      }
      return { ok: true, status: response.status, message: '已发送到收集箱', sourceId }
    }
    let message = `发送失败（${response.status}）`
    try {
      const data = (await response.json()) as { detail?: string }
      if (data.detail) message = data.detail
    } catch {
      // 忽略响应解析失败，保留状态码提示
    }
    return { ok: false, status: response.status, message }
  } catch {
    return { ok: false, status: 0, message: '无法连接 Grove，请检查服务器地址与网络' }
  }
}
