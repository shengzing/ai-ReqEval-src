export interface EncodedProjectFile {
  filename: string
  contentType: string
  content?: string
  contentBase64: string
}

export async function encodeProjectFile(file: File): Promise<EncodedProjectFile> {
  return {
    filename: file.name,
    contentType: file.type || 'application/octet-stream',
    content: file.type.startsWith('text/') ? await file.text() : undefined,
    contentBase64: await readFileAsBase64(file),
  }
}

export function readFileAsBase64(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      const base64 = result.includes(',') ? result.split(',')[1] : result
      resolve(base64)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}
