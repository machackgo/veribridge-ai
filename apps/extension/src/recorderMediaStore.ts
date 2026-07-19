// IndexedDB persistence for finished-but-not-yet-acknowledged recordings.
//
// The recorder tab is a chrome-extension:// page, so its IndexedDB survives
// tab reloads, extension service-worker restarts, and browser restarts.
// A recording blob is written here BEFORE the first upload attempt and deleted
// only after the backend acknowledges the upload — so a failed upload, a
// closed tab, or a crashed worker never loses the only copy of the video.

import type { PendingVideoUpload } from "./recorderFinalize"

const DB_NAME = "veribridge_recorder_media"
const DB_VERSION = 1
const STORE = "pending_video_uploads"

export interface StoredPendingUpload extends PendingVideoUpload {
  blob: Blob
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "session_id" })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error("IndexedDB open failed"))
  })
}

function requestToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error ?? new Error("IndexedDB request failed"))
  })
}

export async function savePendingVideoUpload(entry: StoredPendingUpload): Promise<void> {
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, "readwrite")
    await requestToPromise(tx.objectStore(STORE).put(entry))
  } finally {
    db.close()
  }
}

export async function loadPendingVideoUpload(sessionId: string): Promise<StoredPendingUpload | null> {
  if (!sessionId) return null
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, "readonly")
    const result = await requestToPromise(tx.objectStore(STORE).get(sessionId))
    return (result as StoredPendingUpload | undefined) ?? null
  } finally {
    db.close()
  }
}

export async function deletePendingVideoUpload(sessionId: string): Promise<void> {
  if (!sessionId) return
  const db = await openDb()
  try {
    const tx = db.transaction(STORE, "readwrite")
    await requestToPromise(tx.objectStore(STORE).delete(sessionId))
  } finally {
    db.close()
  }
}
