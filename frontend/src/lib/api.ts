/** 后端 API 客户端：骨架阶段仅提供健康检查。 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export interface HealthPayload {
  status: string
  service?: string
  version?: string
}

/** 调用后端 GET /healthz。 */
export async function fetchHealth(): Promise<HealthPayload> {
  const response = await fetch(`${API_BASE_URL}/healthz`)
  if (!response.ok) {
    throw new Error(`健康检查失败：HTTP ${response.status}`)
  }
  return (await response.json()) as HealthPayload
}
