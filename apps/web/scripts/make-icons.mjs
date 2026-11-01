// Writes the PWA icons (public/icons/*.png) from the logo and cow pixel art
// (features/mascot/cow-art.json) — no image library needed (PNG = zlib + CRC).
// Re-run after editing the art:   node scripts/make-icons.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

const ART = JSON.parse(readFileSync(new URL("../features/mascot/cow-art.json", import.meta.url), "utf8"));
const NAVY = "#10142b"; // the logo's night background
const hex = (c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];

const CRC = new Uint32Array(256).map((_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/**
 * size×size RGBA PNG: `rows` (pixel art) scaled by whole pixels and centred with `padRatio`.
 * `background` null = transparent; `mono` paints every opaque pixel white (notification badge).
 */
function png(rows, size, { padRatio = 0, background = NAVY, mono = false, palette = ART.palette } = {}) {
  const w = rows[0].length;
  const h = rows.length;
  const scale = Math.max(1, Math.floor((size * (1 - 2 * padRatio)) / Math.max(w, h)));
  const ox = Math.floor((size - scale * w) / 2);
  const oy = Math.floor((size - scale * h) / 2);
  const bg = background ? [...hex(background), 255] : [0, 0, 0, 0];
  const lines = [];
  for (let y = 0; y < size; y++) {
    const line = Buffer.alloc(1 + size * 4);
    for (let x = 0; x < size; x++) {
      const gx = Math.floor((x - ox) / scale);
      const gy = Math.floor((y - oy) / scale);
      const key = gx >= 0 && gx < w && gy >= 0 && gy < h ? rows[gy][gx] : ".";
      const rgba = key === "." ? bg : mono ? [255, 255, 255, 255] : [...hex(palette[key]), 255];
      line.set(rgba, 1 + x * 4);
    }
    lines.push(line);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(lines))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const face = ART.face.frames;
const logo = ART.logo.rows;
const L = { palette: ART.logo.palette };
const out = new URL("../public/icons/", import.meta.url);
const icons = [
  // the owner's logo tile (cow in a meadow)
  ["icon-192.png", logo, 192, { ...L }],
  ["icon-512.png", logo, 512, { ...L }],
  ["maskable-512.png", logo, 512, { ...L, padRatio: 0.12 }],
  ["apple-touch-icon.png", logo, 180, { ...L, padRatio: 0.05 }],
  ["favicon-32.png", logo, 32, { ...L }],
  // Android status-bar badge: white silhouette on transparent
  ["badge-96.png", face.idle, 96, { padRatio: 0.04, background: null, mono: true }],
  // offline page
  ["cow-sleep.png", face.sleep, 160, { background: null }],
];
for (const [name, rows, size, options] of icons) writeFileSync(new URL(name, out), png(rows, size, options));
console.log("icons written to public/icons/");
