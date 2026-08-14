import '@testing-library/jest-dom/vitest'

// Node 25 暴露实验性全局 localStorage（非标准实现），会遮蔽 jsdom 的标准 Storage。
// 这里统一兜底为标准的内存 Storage，保证组件对 localStorage 的读写可测。
class MemoryStorage implements Storage {
  private readonly store = new Map<string, string>()

  get length() {
    return this.store.size
  }

  clear() {
    this.store.clear()
  }

  getItem(key: string) {
    return this.store.get(key) ?? null
  }

  key(index: number) {
    return Array.from(this.store.keys())[index] ?? null
  }

  removeItem(key: string) {
    this.store.delete(key)
  }

  setItem(key: string, value: string) {
    this.store.set(key, String(value))
  }
}

function installStorage(target: object) {
  try {
    Object.defineProperty(target, 'localStorage', {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
  } catch {
    ;(target as Record<string, unknown>).localStorage = new MemoryStorage()
  }
}

installStorage(globalThis)
if (typeof window !== 'undefined') installStorage(window)
