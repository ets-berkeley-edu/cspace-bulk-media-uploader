/**
 * What the browser reads from an image file before it uploads it (design: Pre-filling rows from filenames and
 * EXIF): the capture date and the orientation. Both are sent with the request that adds the documents, so the
 * date is pre-filled from the start.
 *
 * Only JPEG and TIFF are read. The date is EXIF DateTimeDigitized, or DateTimeOriginal, or the file's DateTime
 * when those are missing. The orientation comes from the pixel size (the JPEG frame header, or TIFF's
 * ImageWidth/ImageLength), turned by the EXIF Orientation tag (5 to 8 mean the camera was rotated 90°).
 * The reader reads small ranges of the file, never the whole file.
 */

export type Orientation = 'portrait' | 'landscape' | 'square' | '';
export interface ImageInfo {
  date: string; // YYYY-MM-DD, or ""
  orientation: Orientation;
}

type Read = (offset: number, length: number) => Promise<Uint8Array>;

const TAG = {
  imageWidth: 0x0100, imageLength: 0x0101, orientation: 0x0112, dateTime: 0x0132, exifIfd: 0x8769,
  dateTimeOriginal: 0x9003, dateTimeDigitized: 0x9004, pixelX: 0xa002, pixelY: 0xa003,
}
const MAX_ENTRIES = 512

/** The file's capture date and orientation; empty values when it has none or isn't a JPEG or TIFF. */
export async function readImageInfo(file: Blob): Promise<ImageInfo> {
  const read: Read = async (offset, length) => new Uint8Array(await bufferOf(file.slice(offset, offset + length)))
  try {
    return await imageInfo(read, file.size)
  } catch {
    return {date: '', orientation: ''}
  }
}

/** A Blob's bytes (FileReader where Blob.arrayBuffer is missing, as in older engines and jsdom). */
function bufferOf(b: Blob): Promise<ArrayBuffer> {
  if (typeof b.arrayBuffer === 'function') return b.arrayBuffer()
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as ArrayBuffer)
    r.onerror = () => reject(r.error)
    r.readAsArrayBuffer(b)
  })
}

export async function imageInfo(read: Read, size: number): Promise<ImageInfo> {
  const head = await read(0, 4)
  if (head[0] === 0xff && head[1] === 0xd8) return jpegInfo(read, size)
  if ((head[0] === 0x49 && head[1] === 0x49 && head[2] === 0x2a) || (head[0] === 0x4d && head[1] === 0x4d && head[3] === 0x2a)) {
    const t = await tiffTags(read, 0)
    return finish(t, t.width, t.height)
  }
  return {date: '', orientation: ''}
}

async function jpegInfo(read: Read, size: number): Promise<ImageInfo> {
  let pos = 2
  let tags: Tags | null = null
  let width = 0
  let height = 0
  for (let i = 0; i < 200 && pos + 4 <= size; i++) {
    const h = await read(pos, 4)
    if (h[0] !== 0xff) break
    const marker = h[1]
    if (marker === 0xd9 || marker === 0xda) break // end of image, or start of the compressed data
    const len = (h[2] << 8) | h[3]
    if (marker === 0xe1 && !tags) {
      const seg = await read(pos + 4, Math.min(len - 2, 256 * 1024))
      if (seg.length > 6 && String.fromCharCode(...seg.subarray(0, 6)) === 'Exif\u0000\u0000') {
        const tiff = seg.subarray(6)
        tags = await tiffTags(async (o, l) => tiff.subarray(o, o + l), 0)
      }
    } else if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      const f = await read(pos + 4, 5) // precision, height, width
      height = (f[1] << 8) | f[2]
      width = (f[3] << 8) | f[4]
    }
    if (tags && width) break
    pos += 2 + len
  }
  return finish(tags ?? emptyTags(), width || tags?.width || 0, height || tags?.height || 0)
}

interface Tags { dateTime: string; original: string; digitized: string; orientation: number; width: number; height: number }
const emptyTags = (): Tags => ({dateTime: '', original: '', digitized: '', orientation: 0, width: 0, height: 0})

/** Tags from a TIFF structure starting at base (a TIFF file, or the TIFF block inside a JPEG's Exif segment). */
async function tiffTags(read: Read, base: number): Promise<Tags> {
  const hdr = await read(base, 8)
  const le = hdr[0] === 0x49
  const u16 = (b: Uint8Array, o: number) => (le ? b[o] | (b[o + 1] << 8) : (b[o] << 8) | b[o + 1])
  const u32 = (b: Uint8Array, o: number) => (le ? (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)) + b[o + 3] * 2 ** 24
    : ((b[o] << 16) | (b[o + 1] << 8) | b[o + 2]) * 256 + b[o + 3])
  const out = emptyTags()

  async function ifd(offset: number): Promise<number> {
    const countBytes = await read(base + offset, 2)
    if (countBytes.length < 2) return 0
    const n = Math.min(u16(countBytes, 0), MAX_ENTRIES)
    const entries = await read(base + offset + 2, n * 12)
    let exifIfd = 0
    for (let i = 0; i + 12 <= entries.length; i += 12) {
      const tag = u16(entries, i)
      const type = u16(entries, i + 2)
      const count = u32(entries, i + 4)
      const num = () => (type === 3 ? u16(entries, i + 8) : u32(entries, i + 8))
      const ascii = async () => {
        const bytes = count <= 4 ? entries.subarray(i + 8, i + 8 + count) : await read(base + u32(entries, i + 8), Math.min(count, 64))
        // eslint-disable-next-line no-control-regex
        return String.fromCharCode(...bytes).replace(/\u0000.*$/, '')
      }
      if (tag === TAG.dateTime && type === 2) out.dateTime = await ascii()
      else if (tag === TAG.dateTimeOriginal && type === 2) out.original = await ascii()
      else if (tag === TAG.dateTimeDigitized && type === 2) out.digitized = await ascii()
      else if (tag === TAG.orientation) out.orientation = num()
      else if ((tag === TAG.imageWidth || tag === TAG.pixelX) && !out.width) out.width = num()
      else if ((tag === TAG.imageLength || tag === TAG.pixelY) && !out.height) out.height = num()
      else if (tag === TAG.exifIfd) exifIfd = u32(entries, i + 8)
    }
    return exifIfd
  }

  const exif = await ifd(u32(hdr, 4))
  if (exif) await ifd(exif)
  return out
}

const EXIF_DATE = /^(\d{4}):(\d{2}):(\d{2})/

function finish(t: Tags, width: number, height: number): ImageInfo {
  const raw = [t.digitized, t.original, t.dateTime].find((d) => EXIF_DATE.test(d) && !d.startsWith('0000')) ?? ''
  const m = EXIF_DATE.exec(raw)
  const date = m ? `${m[1]}-${m[2]}-${m[3]}` : ''
  const turned = t.orientation >= 5 && t.orientation <= 8
  const [w, h] = turned ? [height, width] : [width, height]
  const orientation: Orientation = !w || !h ? '' : w > h ? 'landscape' : h > w ? 'portrait' : 'square'
  return {date, orientation}
}
