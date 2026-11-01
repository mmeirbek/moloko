// Writes the PWA icons (public/icons/*.png) from the placeholder pixel mark in
// components/brand/logo.tsx — no image library needed (PNG = zlib + CRC).
// When the owner's logo arrives, replace PIXELS below (or the PNGs) and re-run:
//   node scripts/make-icons.mjs
import { writeFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

const RECTS = [
  [0, 0, 16, 16, "#f6efdc"], [1, 1, 14, 9, "#4aa8e8"], [3, 3, 4, 1, "#ffffff"], [4, 2, 2, 1, "#ffffff"],
  [10, 4, 3, 1, "#ffffff"], [1, 10, 14, 3, "#5bbf4a"], [1, 13, 14, 2, "#6b4a2f"], [5, 7, 6, 3, "#ffffff"],
  [6, 8, 2, 1, "#3b2a24"], [11, 6, 2, 2, "#ffffff"], [5, 10, 1, 1, "#3b2a24"], [10, 10, 1, 1, "#3b2a24"],
];

function grid() {
  const g = Array.from({ length: 16 }, () => Array(16).fill("#f6efdc"));
  for (const [x, y, w, h, c] of RECTS) for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) g[j][i] = c;
  return g;
}

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

/** size×size PNG; the 16×16 mark scaled by whole pixels, centred with `pad` (maskable). */
function png(size, padRatio) {
  const g = grid();
  const scale = Math.floor((size * (1 - 2 * padRatio)) / 16);
  const offset = Math.floor((size - scale * 16) / 2);
  const rows = [];
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 3);
    for (let x = 0; x < size; x++) {
      const gx = Math.floor((x - offset) / scale), gy = Math.floor((y - offset) / scale);
      const c = gx >= 0 && gx < 16 && gy >= 0 && gy < 16 ? g[gy][gx] : "#f6efdc";
      row[1 + x * 3] = parseInt(c.slice(1, 3), 16);
      row[2 + x * 3] = parseInt(c.slice(3, 5), 16);
      row[3 + x * 3] = parseInt(c.slice(5, 7), 16);
    }
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const out = new URL("../public/icons/", import.meta.url);
for (const [name, size, pad] of [["icon-192.png", 192, 0], ["icon-512.png", 512, 0], ["maskable-512.png", 512, 0.12], ["apple-touch-icon.png", 180, 0.06], ["favicon-32.png", 32, 0]]) {
  writeFileSync(new URL(name, out), png(size, pad));
}
console.log("icons written to public/icons/");
