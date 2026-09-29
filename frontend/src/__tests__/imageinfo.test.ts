import { describe, expect, it } from "vitest";
import { imageInfo, readImageInfo } from "../lib/imageinfo";
import { FIXTURES } from "./imagefixtures";

const bytes = (b64: string) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
const info = (b64: string) => {
  const b = bytes(b64);
  return imageInfo(async (o, l) => b.subarray(o, o + l), b.length);
};

describe("EXIF date and orientation (design: Pre-filling rows from filenames and EXIF)", () => {
  it("uses DateTimeDigitized, and the frame size for the orientation", async () => {
    expect(await info(FIXTURES.landscapeDigitized)).toEqual({ date: "2024-05-17", orientation: "landscape" });
  });
  it("falls back to DateTimeOriginal, and turns the orientation when the camera was rotated", async () => {
    expect(await info(FIXTURES.rotatedPortrait)).toEqual({ date: "2023-01-02", orientation: "portrait" });
  });
  it("reads TIFF files, falling back to DateTime", async () => {
    expect(await info(FIXTURES.tiffPortrait)).toEqual({ date: "2021-07-08", orientation: "portrait" });
  });
  it("gives no date for an image without EXIF, and nothing for other files", async () => {
    expect(await info(FIXTURES.noExif)).toEqual({ date: "", orientation: "square" });
    expect(await readImageInfo(new Blob(["RIFF....WAVEfmt "]))).toEqual({ date: "", orientation: "" });
    expect(await readImageInfo(new Blob([bytes(FIXTURES.landscapeDigitized)]))).toEqual({ date: "2024-05-17", orientation: "landscape" });
  });
});
