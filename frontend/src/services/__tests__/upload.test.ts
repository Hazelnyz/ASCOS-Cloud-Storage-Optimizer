import { describe, it, expect } from 'vitest'
import { validateUploadFile, MAX_SINGLE_PUT_BYTES, MAX_FILENAME_LENGTH } from '../upload'
import { ApiError } from '../errors'

function makeFile(name: string, size: number): File {
  return new File([new Uint8Array(Math.min(size, 1024))], name, { type: 'text/plain' })
}

describe('validateUploadFile', () => {
  it('accepts an ordinary file', () => {
    expect(() => validateUploadFile(makeFile('report.pdf', 1024))).not.toThrow()
  })

  it('accepts a non-ASCII filename at the client validation layer (the encoding fix happens server-side)', () => {
    expect(() => validateUploadFile(makeFile('résumé.pdf', 1024))).not.toThrow()
  })

  it('rejects a file over the single-PUT size limit', () => {
    const big = makeFile('big.bin', 0)
    Object.defineProperty(big, 'size', { value: MAX_SINGLE_PUT_BYTES + 1 })
    expect(() => validateUploadFile(big)).toThrow(ApiError)
  })

  it('rejects a filename longer than the limit', () => {
    expect(() => validateUploadFile(makeFile('a'.repeat(MAX_FILENAME_LENGTH + 1) + '.txt', 10))).toThrow(ApiError)
  })
})
