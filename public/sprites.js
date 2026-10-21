// Пиксельные спрайты офиса. Всё рисуется кодом по «картам» из символов — без сторонних картинок,
// поэтому никаких вопросов с лицензиями на арт.

export const PAL = {
  ink: "#141022",
  outline: "#241a33",
  wood: "#a0603a",
  woodLight: "#c98250",
  woodDark: "#6b3a26",
  metal: "#5f5a6e",
  metalLight: "#8b86a0",
  screenOff: "#1d2440",
  screenBg: "#0b1020",
  key: "#c2c3c7",
  keyDark: "#8a8b94",
  chair: "#3b2f52",
  chairLight: "#52437a",
  mug: "#fff1e8",
  plant: "#2f9e5b",
  plantLight: "#5fd07e",
  pot: "#b0563a",
  yellow: "#ffd23f",
  blue: "#3ab7ff",
};

const SKINS = ["#ffd1aa", "#f2b38a", "#d08b5b", "#a8693f", "#7a4a2a"];
const HAIRS = ["#2b1d14", "#5a3a22", "#a86a2c", "#e3b04b", "#d9603b", "#3c3c48", "#8f5fc9", "#e8e8f0"];
const STYLES = ["short", "long", "bun", "spiky"];

// ---------- Карты пикселей (10 точек в ширину) ----------
// o — контур, h — волосы, s — кожа, e — глаз, m — рот/тень кожи, c — рубашка, d — тень рубашки

const HEAD = {
  short: [
    "..oooooo..",
    ".ohhhhhho.",
    "ohhhhhhhho",
    "ohssssssho",
    "osesssseso",
    "osssssssso",
    ".ossmmsso.",
  ],
  long: [
    "..oooooo..",
    ".ohhhhhho.",
    "ohhhhhhhho",
    "ohssssssho",
    "ohesssseho",
    "ohssssssho",
    "ohssmmssho",
  ],
  bun: [
    "..oooooo..",
    ".ohhhhhho.",
    "ohhhhhhhho",
    "ohssssssho",
    "osesssseso",
    "osssssssso",
    ".ossmmsso.",
  ],
  spiky: [
    ".o.o.o.o..",
    "ohohohoho.",
    "ohhhhhhhho",
    "ohssssssho",
    "osesssseso",
    "osssssssso",
    ".ossmmsso.",
  ],
};

const BUN_TOP = ["...oooo...", "..ohhhho.."];

const BODY = [
  "...osso...",
  ".occcccco.",
  "occcccccco",
  "ocdccccdco",
  "ocdccccdco",
];

// ---------- Утилиты ----------

function hash(str) {
  let h = 2166136261;
  for (const ch of String(str)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

function shade(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v + amount)));
  const r = f(n >> 16), g = f((n >> 8) & 255), b = f(n & 255);
  return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
}

function rect(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

function paint(ctx, map, x, y, colors) {
  map.forEach((row, j) => {
    for (let i = 0; i < row.length; i++) {
      const c = colors[row[i]];
      if (c) rect(ctx, x + i, y + j, 1, 1, c);
    }
  });
}

// Внешность сотрудника выводится из его id: у каждого своя причёска и цвет волос, рубашка — цвет агента.
export function lookFor(agent) {
  const h = hash(agent.id);
  return {
    skin: SKINS[h % SKINS.length],
    hair: HAIRS[(h >>> 3) % HAIRS.length],
    style: STYLES[(h >>> 7) % STYLES.length],
    shirt: agent.color || "#7c8cff",
  };
}

function charColors(look, eyesClosed) {
  return {
    o: PAL.outline,
    h: look.hair,
    s: look.skin,
    e: eyesClosed ? shade(look.skin, -60) : PAL.ink,
    m: shade(look.skin, -35),
    c: look.shirt,
    d: shade(look.shirt, -40),
  };
}

function drawCharacter(ctx, look, x, y, { eyesClosed = false } = {}) {
  const colors = charColors(look, eyesClosed);
  if (look.style === "bun") paint(ctx, BUN_TOP, x, y - 2, colors);
  paint(ctx, HEAD[look.style], x, y, colors);
  paint(ctx, BODY, x, y + 7, colors);
}

// ---------- Сцена рабочего места: 48×40 ----------

export const DESK_W = 48;
export const DESK_H = 40;

export function drawDesk(canvas, agent, frame) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, DESK_W, DESK_H);
  const look = lookFor(agent);
  const status = agent.status;
  const working = status === "working";
  const waiting = status === "waiting";
  const idle = status === "idle";

  const cx = 22;
  const cy = 6 + (working && frame % 4 < 2 ? 0 : working ? 1 : 0);

  // Спинка кресла
  rect(ctx, cx - 1, 11, 12, 13, PAL.outline);
  rect(ctx, cx, 12, 10, 12, PAL.chair);
  rect(ctx, cx, 12, 10, 1, PAL.chairLight);

  // Сотрудник (у свободного глаза иногда закрываются — дремлет)
  drawCharacter(ctx, look, cx, cy, { eyesClosed: idle && frame % 8 >= 5 });

  // Поднятая рука, когда ждёт ответа
  if (waiting) {
    const up = frame % 2 === 0 ? 0 : 1;
    rect(ctx, cx + 10, cy - 3 + up, 3, 11, PAL.outline);
    rect(ctx, cx + 11, cy + 1 + up, 1, 6, look.shirt);
    rect(ctx, cx + 11, cy - 2 + up, 1, 3, look.skin);
  }

  // Монитор
  rect(ctx, 3, 7, 17, 15, PAL.outline);
  rect(ctx, 4, 8, 15, 13, PAL.metal);
  rect(ctx, 4, 8, 15, 1, PAL.metalLight);
  rect(ctx, 5, 9, 13, 11, idle ? PAL.screenOff : PAL.screenBg);
  rect(ctx, 10, 21, 3, 3, PAL.outline);
  rect(ctx, 11, 21, 1, 3, PAL.metal);

  if (working) {
    // Бегущие строки «кода» цветом агента
    for (let i = 0; i < 5; i++) {
      const len = 3 + ((hash(agent.id + (i + frame)) >>> 4) % 9);
      rect(ctx, 6, 10 + i * 2, len, 1, i % 2 ? look.shirt : shade(look.shirt, 60));
    }
    if (frame % 2) rect(ctx, 6 + ((frame * 3) % 11), 18, 1, 1, "#ffffff");
  } else if (waiting) {
    if (frame % 2 === 0) {
      rect(ctx, 11, 10, 2, 6, PAL.yellow);
      rect(ctx, 11, 17, 2, 2, PAL.yellow);
    }
  } else if (status === "queued") {
    rect(ctx, 7, 11, 9, 6, PAL.blue);
    rect(ctx, 8, 12, 7, 4, PAL.screenBg);
    rect(ctx, 8, 12, 1, 1, PAL.blue);
    rect(ctx, 9, 13, 1, 1, PAL.blue);
    rect(ctx, 10, 14, 3, 1, PAL.blue);
    rect(ctx, 13, 13, 1, 1, PAL.blue);
    rect(ctx, 14, 12, 1, 1, PAL.blue);
  } else {
    rect(ctx, 6, 10, 2, 1, shade(PAL.screenOff, 30)); // блик на выключенном экране
    rect(ctx, 6, 11, 1, 1, shade(PAL.screenOff, 30));
  }

  // Стол
  rect(ctx, 1, 23, 46, 15, PAL.outline);
  rect(ctx, 2, 24, 44, 3, PAL.woodLight);
  rect(ctx, 2, 27, 44, 10, PAL.wood);
  rect(ctx, 2, 27, 44, 1, PAL.woodDark);
  rect(ctx, 6, 30, 12, 5, PAL.woodDark); // ящик
  rect(ctx, 11, 32, 2, 1, PAL.woodLight);

  // Клавиатура и руки
  rect(ctx, 20, 22, 14, 3, PAL.outline);
  rect(ctx, 21, 23, 12, 1, PAL.key);
  for (let k = 0; k < 6; k++) rect(ctx, 21 + k * 2, 23, 1, 1, PAL.keyDark);
  if (!waiting) {
    const lh = working && frame % 2 ? -1 : 0;
    const rh = working && frame % 2 === 0 ? -1 : 0;
    rect(ctx, 22, 21 + lh, 3, 2, PAL.outline);
    rect(ctx, 23, 21 + lh, 1, 1, look.skin);
    rect(ctx, 29, 21 + rh, 3, 2, PAL.outline);
    rect(ctx, 30, 21 + rh, 1, 1, look.skin);
  }

  // Кружка (с паром, когда работа кипит)
  rect(ctx, 36, 19, 5, 5, PAL.outline);
  rect(ctx, 37, 20, 3, 3, PAL.mug);
  rect(ctx, 37, 20, 3, 1, PAL.woodDark);
  rect(ctx, 41, 20, 1, 2, PAL.outline);
  if (working) {
    const s = frame % 3;
    rect(ctx, 37 + (s % 2), 16 - s, 1, 2, "#d9d4e8");
    rect(ctx, 39 - (s % 2), 15 - s, 1, 2, "#b8b2cc");
  }

  // Растение у части столов — для разнообразия
  if (hash(agent.id) % 2) {
    rect(ctx, 42, 18, 5, 6, PAL.outline);
    rect(ctx, 43, 19, 3, 4, PAL.pot);
    rect(ctx, 42, 13, 5, 5, PAL.plant);
    rect(ctx, 43, 12, 3, 2, PAL.plantLight);
    rect(ctx, 44, 11, 1, 1, PAL.plantLight);
  }
}

// ---------- Портрет 12×12 для чата и списков ----------

const portraitCache = new Map();

export function portrait(agent) {
  const look = lookFor(agent);
  const key = `${agent.id}|${look.shirt}`;
  if (portraitCache.has(key)) return portraitCache.get(key);
  const c = document.createElement("canvas");
  c.width = 12;
  c.height = 12;
  const ctx = c.getContext("2d");
  rect(ctx, 0, 0, 12, 12, shade(look.shirt, -90));
  drawCharacter(ctx, look, 1, look.style === "bun" ? 2 : 1);
  const url = c.toDataURL();
  portraitCache.set(key, url);
  return url;
}

// ---------- Иконки 10×10 ----------

const ICONS = {
  office: [
    ".oooooooo.",
    ".owywwywo.",
    ".owwwwwwo.",
    ".owywwywo.",
    ".owwwwwwo.",
    ".owywwywo.",
    ".owwddwwo.",
    ".owwddwwo.",
    "oooooooooo",
    "..........",
  ],
  chat: [
    ".oooooooo.",
    "owwwwwwwwo",
    "owwwwwwwwo",
    "owkwkwkwwo",
    "owwwwwwwwo",
    "owwwwwwwwo",
    ".ooowoooo.",
    "...owo....",
    "...oo.....",
    "..........",
  ],
  tasks: [
    "...oooo...",
    ".oooyyooo.",
    ".owwwwwwo.",
    ".owkkkkwo.",
    ".owwwwwwo.",
    ".owkkkwwo.",
    ".owwwwwwo.",
    ".owkkkkwo.",
    ".owwwwwwo.",
    ".oooooooo.",
  ],
  files: [
    "ooooooooo.",
    "obllldllbo",
    "obllldllbo",
    "obbbbbbbbo",
    "obbbbbbbbo",
    "obwwwwwwbo",
    "obwkkkkwbo",
    "obwwwwwwbo",
    "obwwwwwwbo",
    "oooooooooo",
  ],
  bell: [
    "....oo....",
    "...oyyo...",
    "..oyyyyo..",
    "..oyyyyo..",
    ".oyyyyyyo.",
    ".oyyyyyyo.",
    "oyyyyyyyyo",
    "oooooooooo",
    "....oo....",
    "..........",
  ],
  team: [
    "...oooo...",
    "..osssso..",
    "..osesso..",
    "..osssso..",
    "...oooo...",
    ".oooooooo.",
    "occcccccco",
    "occcccccco",
    "occcccccco",
    "oooooooooo",
  ],
};

const ICON_COLORS = {
  o: PAL.outline,
  w: "#fff1e8",
  y: "#ffd23f",
  d: "#a0603a",
  k: "#5f5a6e",
  b: "#3a6cff",
  l: "#c2c3c7",
  s: "#ffd1aa",
  e: PAL.ink,
  c: "#ff6b8b",
};

const iconCache = new Map();

export function icon(name) {
  if (iconCache.has(name)) return iconCache.get(name);
  const c = document.createElement("canvas");
  c.width = 10;
  c.height = 10;
  paint(c.getContext("2d"), ICONS[name], 0, 0, ICON_COLORS);
  const url = c.toDataURL();
  iconCache.set(name, url);
  return url;
}
