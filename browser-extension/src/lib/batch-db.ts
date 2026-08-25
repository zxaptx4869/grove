/** 批次图片存储：IndexedDB 保存图片 Blob，避免 chrome.storage 配额限制。 */

const DB_NAME = 'grove-capture-db'
const DB_VERSION = 1
const IMAGE_STORE = 'images'
const META_STORE = 'meta'
const BATCH_KEY = 'currentBatch'
const PENDING_KEY = 'pendingPreview'

export interface BatchImage {
  id: number
  createdAt: number
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(IMAGE_STORE)) {
        db.createObjectStore(IMAGE_STORE, { keyPath: 'id', autoIncrement: true })
      }
      if (!db.objectStoreNames.contains(META_STORE)) {
        db.createObjectStore(META_STORE)
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function readBatchIds(): Promise<number[]> {
  const db = await openDb()
  return new Promise<number[]>((resolve, reject) => {
    const tx = db.transaction(META_STORE, 'readonly')
    const get = tx.objectStore(META_STORE).get(BATCH_KEY)
    tx.oncomplete = () => {
      db.close()
      resolve((get.result as number[] | undefined) ?? [])
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function addBatchImage(blob: Blob): Promise<BatchImage> {
  const db = await openDb()
  return new Promise<BatchImage>((resolve, reject) => {
    const tx = db.transaction([IMAGE_STORE, META_STORE], 'readwrite')
    const imageStore = tx.objectStore(IMAGE_STORE)
    const metaStore = tx.objectStore(META_STORE)
    let imageId: number | undefined
    const put = imageStore.put({ blob, createdAt: Date.now() })
    put.onsuccess = () => {
      imageId = put.result as number
    }
    const getIds = metaStore.get(BATCH_KEY)
    getIds.onsuccess = () => {
      const ids = ((getIds.result as number[] | undefined) ?? []).slice()
      if (imageId != null) ids.push(imageId)
      metaStore.put(ids, BATCH_KEY)
    }
    tx.oncomplete = () => {
      db.close()
      resolve({ id: imageId as number, createdAt: Date.now() })
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function getBatchImages(): Promise<BatchImage[]> {
  const ids = await readBatchIds()
  return ids.map((id) => ({ id, createdAt: 0 }))
}

export async function getImageBlob(id: number): Promise<Blob> {
  const db = await openDb()
  return new Promise<Blob>((resolve, reject) => {
    const tx = db.transaction(IMAGE_STORE, 'readonly')
    const get = tx.objectStore(IMAGE_STORE).get(id)
    tx.oncomplete = () => {
      db.close()
      const record = get.result as { blob: Blob } | undefined
      if (record) resolve(record.blob)
      else reject(new Error('批次图片不存在'))
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function removeBatchImage(id: number): Promise<void> {
  const ids = await readBatchIds()
  const next = ids.filter((item) => item !== id)
  const db = await openDb()
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction([IMAGE_STORE, META_STORE], 'readwrite')
    tx.objectStore(META_STORE).put(next, BATCH_KEY)
    tx.objectStore(IMAGE_STORE).delete(id)
    tx.oncomplete = () => {
      db.close()
      resolve()
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function clearBatch(): Promise<void> {
  const db = await openDb()
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction([IMAGE_STORE, META_STORE], 'readwrite')
    tx.objectStore(META_STORE).put([], BATCH_KEY)
    tx.objectStore(IMAGE_STORE).clear()
    tx.oncomplete = () => {
      db.close()
      resolve()
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function savePendingBlob(blob: Blob): Promise<void> {
  const db = await openDb()
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction(META_STORE, 'readwrite')
    tx.objectStore(META_STORE).put(blob, PENDING_KEY)
    tx.oncomplete = () => {
      db.close()
      resolve()
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function getPendingBlob(): Promise<Blob | null> {
  const db = await openDb()
  return new Promise<Blob | null>((resolve, reject) => {
    const tx = db.transaction(META_STORE, 'readonly')
    const get = tx.objectStore(META_STORE).get(PENDING_KEY)
    tx.oncomplete = () => {
      db.close()
      resolve((get.result as Blob | undefined) ?? null)
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export async function clearPendingBlob(): Promise<void> {
  const db = await openDb()
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction(META_STORE, 'readwrite')
    tx.objectStore(META_STORE).delete(PENDING_KEY)
    tx.oncomplete = () => {
      db.close()
      resolve()
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}
