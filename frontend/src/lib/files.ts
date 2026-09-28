/** Browser-side file helpers: EXIF capture date, previews and the direct upload to S3. */

const EXIF_DATE = /(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})/;

/** Find an EXIF date (YYYY:MM:DD HH:MM:SS) near the start of the file; "" if none. Returns YYYY-MM-DD. */
export async function readExifDate(file: Blob): Promise<string> {
  try {
    const buf = new Uint8Array(await file.slice(0, 256 * 1024).arrayBuffer());
    return exifDateFromBytes(buf);
  } catch {
    return "";
  }
}

export function exifDateFromBytes(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
  const m = EXIF_DATE.exec(text);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}

export function canPreview(file: File): boolean {
  return /^image\/(jpeg|png|gif|webp)$/i.test(file.type);
}

/** Upload one file with a presigned POST, reporting progress (0–100). */
export function uploadToS3(
  form: { url: string; fields: Record<string, string> },
  file: File,
  onProgress: (pct: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    Object.entries(form.fields).forEach(([k, v]) => data.append(k, v));
    data.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.url);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Upload failed (network)"));
    xhr.send(data);
  });
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function formatTime(epochSeconds?: number): string {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
