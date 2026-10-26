import { api } from './api'
import type { Attachment } from './types'

const MAX_BYTES = 10_000_000

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result).split(',', 2)[1] ?? '')
    r.onerror = () => reject(new Error('Could not read the file.'))
    r.readAsDataURL(file)
  })
}

/** Upload a client document (PDF/TXT/MD). The server extracts and safety-screens the text. */
export async function uploadDocument(file: File): Promise<Attachment> {
  if (file.size > MAX_BYTES) throw new Error(`${file.name} is ${(file.size / 1e6).toFixed(1)} MB; the limit is 10 MB.`)
  if (!/\.(pdf|txt|md|eml)$/i.test(file.name)) throw new Error('Upload a PDF, TXT or Markdown file. (Word: save as PDF first.)')
  return api.post<Attachment>('/api/files', { filename: file.name, data_base64: await toBase64(file) })
}

export const ACCEPT = '.pdf,.txt,.md,.eml'
