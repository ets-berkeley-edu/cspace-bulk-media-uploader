/** Browser-side file helpers: previews and the direct upload to S3. (EXIF: see imageinfo.ts.) */

/** Run fn over items, at most limit at a time, keeping the results in order. */
export async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const lane = async () => {
    for (let i = next++; i < items.length; i = next++) out[i] = await fn(items[i]);
  };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane));
  return out;
}

export function canPreview(file: File): boolean {
  return /^image\/(jpeg|png|gif|webp)$/i.test(file.type);
}

/** An upload stopped on purpose (its document was deleted), not a failure. */
export class UploadCancelled extends Error {
  constructor() {
    super("Upload cancelled");
    this.name = "UploadCancelled";
  }
}

/** Upload one file with a presigned POST, reporting progress (0–100). An abort signal stops it at once: S3 keeps
 * nothing of a POST that didn't finish, and the promise rejects with UploadCancelled. */
export function uploadToS3(
  form: { url: string; fields: Record<string, string> },
  file: File,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new UploadCancelled());
    const data = new FormData();
    Object.entries(form.fields).forEach(([k, v]) => data.append(k, v));
    data.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.url);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("Upload failed (network)"));
    xhr.onabort = () => reject(new UploadCancelled());
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
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

/**
 * A thumbnail made in the browser from the local file (JPEG and PNG; design: Thumbnails): at most 320 px on
 * its longer side, drawn on a canvas and saved as a JPEG, which carries no EXIF or other metadata. null if the
 * browser can't draw it.
 */
export async function makeThumbnail(file: File, maxSide = 320): Promise<Blob | null> {
  if (!canPreview(file) || typeof createImageBitmap !== "function") return null;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bmp.width * scale));
    canvas.height = Math.max(1, Math.round(bmp.height * scale));
    canvas.getContext("2d")?.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close();
    return await new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/jpeg", 0.8));
  } catch {
    return null;
  }
}

/** What to show for a file the browser can't draw: its kind (design: video, audio and 3D files show a type icon). */
export function fileKind(name: string): { icon: string; label: string; image: boolean } {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  if (["wav", "mp3", "aac"].includes(ext)) return { icon: "♪", label: "Audio", image: false };
  if (ext === "mp4") return { icon: "▶", label: "Video", image: false };
  if (ext === "x3d") return { icon: "⬡", label: "3D model", image: false };
  if (ext === "pdf") return { icon: "PDF", label: "PDF document", image: false };
  return { icon: ext.toUpperCase() || "FILE", label: ext.toUpperCase() || "File", image: ["jpg", "jpeg", "png", "tif", "tiff"].includes(ext) };
}

/** Split chosen files into the ones the BMU accepts and the ones it skips (design: Supported file types).
 *  Skipped files are never uploaded; the server's row check is the backstop. No list means accept all. */
export function splitSupported<T extends { name: string }>(files: T[], types: string[] | undefined): { ok: T[]; skipped: T[] } {
  if (!types?.length) return { ok: files, skipped: [] };
  const allowed = new Set(types.map((t) => t.toLowerCase()));
  const ext = (n: string) => (n.includes(".") ? n.split(".").pop()!.toLowerCase() : "");
  const ok: T[] = [];
  const skipped: T[] = [];
  for (const f of files) (allowed.has(ext(f.name)) ? ok : skipped).push(f);
  return { ok, skipped };
}

/** The message for files skipped because of their type. */
export function skippedText(names: string[], hint: string | undefined): string {
  const shown = names.slice(0, 5).join(", ") + (names.length > 5 ? `, and ${names.length - 5} more` : "");
  return `${names.length} file${names.length === 1 ? "" : "s"} skipped: ${shown}. The BMU accepts ${hint || "only supported file types"}.`;
}
