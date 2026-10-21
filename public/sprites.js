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
  green: "#5fd07e",
  red: "#ff4d6d",
  blue: "#3ab7ff",
  white: "#fff8e6",
};

const SKINS = ["#ffd1aa", "#f2b38a", "#d08b5b", "#a8693f", "#7a4a2a"];
const HAIRS = ["#2b1d14", "#5a3a22", "#a86a2c", "#e3b04b", "#d9603b", "#3c3c48", "#8f5fc9", "#e8e8f0"];
const PANTS = ["#2c3e66", "#3b3b48", "#4a3226", "#2f4f3a", "#5a2e4a"];
const STYLES = ["short", "long", "bun", "spiky"];

// ---------- Карты пикселей (10 точек в ширину) ----------
// o — контур, h — волосы, s — кожа, e — глаз, m — рот/тень кожи, c — рубашка, d — тень рубашки, p — брюки, k — обувь

const HEAD = {
  short: ["..oooooo..", ".ohhhhhho.", "ohhhhhhhho", "ohssssssho", "osesssseso", "osssssssso", ".ossmmsso."],
  long: ["..oooooo..", ".ohhhhhho.", "ohhhhhhhho", "ohssssssho", "ohesssseho", "ohssssssho", "ohssmmssho"],
  bun: ["..oooooo..", ".ohhhhhho.", "ohhhhhhhho", "ohssssssho", "osesssseso", "osssssssso", ".ossmmsso."],
  spiky: [".o.o.o.o..", "ohohohoho.", "ohhhhhhhho", "ohssssssho", "osesssseso", "osssssssso", ".ossmmsso."],
};
const BUN_TOP = ["...oooo...", "..ohhhho.."];
const BODY = ["...osso...", ".occcccco.", "occcccccco", "ocdccccdco", "ocdccccdco"];
const LEGS = [
  ["..oppppo..", "..opoopo..", "..okooko.."],
  ["..oppppo..", ".opo..opo.", ".oko..oko."],
];

// ---------- Утилиты ----------

export function hash(str) {
  let h = 2166136261;
  for (const ch of String(str)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

export function shade(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v + amount)));
  const r = f(n >> 16), g = f((n >> 8) & 255), b = f(n & 255);
  return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
}

export function mix(a, b, t) {
  const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
  const ch = (s) => Math.round(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t);
  return "#" + ((ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).padStart(6, "0");
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

// Внешность выводится из id: у каждого своя причёска, кожа и брюки; рубашка — цвет отдела.
export function lookFor(member) {
  const h = hash(member.id);
  return {
    skin: SKINS[h % SKINS.length],
    hair: HAIRS[(h >>> 3) % HAIRS.length],
    style: STYLES[(h >>> 7) % STYLES.length],
    pants: PANTS[(h >>> 11) % PANTS.length],
    shirt: member.color || "#7c8cff",
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
    p: look.pants,
    k: PAL.ink,
  };
}

function drawCharacter(ctx, look, x, y, { eyesClosed = false, standing = false, step = 0 } = {}) {
  const colors = charColors(look, eyesClosed);
  if (look.style === "bun") paint(ctx, BUN_TOP, x, y - 2, colors);
  paint(ctx, HEAD[look.style], x, y, colors);
  paint(ctx, BODY, x, y + 7, colors);
  if (standing) paint(ctx, LEGS[step % 2], x, y + 12, colors);
}

// ---------- Пиксельные значки в пузырях 5×5 ----------

const GLYPHS = {
  check: ["....o", "...o.", "o.o..", ".o...", "....."],
  question: [".ooo.", "...o.", "..o..", ".....", "..o.."],
  zzz: ["oooo.", "..o..", ".o...", "oooo.", "....."],
};

function bubble(ctx, cx, top, kind, frame) {
  // cx — центр персонажа, top — верх головы
  const x = cx - 4, y = top - 10;
  const bg = kind === "question" ? PAL.yellow : PAL.white;
  rect(ctx, x, y, 9, 7, PAL.outline);
  rect(ctx, x + 1, y + 1, 7, 5, bg);
  rect(ctx, cx, y + 7, 1, 1, PAL.outline); // хвостик
  if (kind === "dots") {
    for (let i = 0; i < 3; i++) rect(ctx, x + 2 + i * 2, y + 3, 1, 1, i === frame % 3 ? PAL.ink : PAL.metalLight);
  } else {
    paint(ctx, GLYPHS[kind], x + 2, y + 1, { o: kind === "check" ? "#1f9e4d" : PAL.ink });
  }
}

// ---------- Комната отдела: 176×84 ----------

export const ROOM_W = 176;
export const ROOM_H = 84;
const SIT_Y = 50;
const LOUNGE_Y = 28;
const DESK_TOP = 62;

// Где стоят столы и где ждут свободные сотрудники — зависит от числа субагентов (1–4).
export function roomLayout(n) {
  const count = Math.max(1, Math.min(4, n));
  const offset = Math.round((ROOM_W - (count * 42 - 6)) / 2);
  const desks = Array.from({ length: count }, (_, i) => offset + i * 42);
  return {
    desks,
    seats: desks.map((x0) => ({ x: x0 + 15, y: SIT_Y })),
    lounge: Array.from({ length: count }, (_, i) => ({ x: 48 + i * 20, y: LOUNGE_Y })),
  };
}

function drawWall(ctx, color, sky, runs, frame) {
  const wall = mix(color, "#1a1428", 0.72);
  for (let x = 0; x < ROOM_W; x += 8) rect(ctx, x, 0, 8, 24, (x / 8) % 2 ? wall : shade(wall, 8));
  rect(ctx, 0, 24, ROOM_W, 2, PAL.outline);

  // Окно с настоящим небом
  rect(ctx, 6, 4, 24, 16, PAL.outline);
  rect(ctx, 7, 5, 22, 14, sky.top);
  rect(ctx, 7, 12, 22, 7, sky.bottom);
  if (sky.night) {
    [[9, 7], [15, 9], [24, 6], [20, 14], [11, 15]].forEach(([sx, sy], i) => rect(ctx, sx, sy, 1, 1, (frame + i) % 6 ? "#fff" : "#8b86a0"));
  } else {
    rect(ctx, 22, sky.evening ? 13 : 7, 4, 4, sky.evening ? "#ffb13b" : "#fff3a0");
  }
  rect(ctx, 17, 5, 2, 14, PAL.metalLight);
  rect(ctx, 7, 11, 22, 1, PAL.metalLight);

  // Доска задач: квадратик на каждого вызванного субагента
  rect(ctx, 62, 3, 52, 18, PAL.outline);
  rect(ctx, 63, 4, 50, 16, "#e9e4f2");
  rect(ctx, 63, 19, 50, 1, "#b8b2cc");
  if (!runs.length) {
    rect(ctx, 67, 8, 22, 1, "#c9c3d9");
    rect(ctx, 67, 12, 32, 1, "#c9c3d9");
    rect(ctx, 67, 16, 16, 1, "#c9c3d9");
  }
  runs.slice(-14).forEach((r, i) => {
    const x = 66 + (i % 7) * 7, y = 7 + Math.floor(i / 7) * 6;
    const c = r.status === "done" ? PAL.green : r.status === "failed" ? PAL.red : frame % 2 ? PAL.yellow : "#ffe98a";
    rect(ctx, x, y, 5, 4, PAL.outline);
    rect(ctx, x + 1, y + 1, 3, 2, c);
  });

  // Дверь
  rect(ctx, 152, 5, 17, 21, PAL.outline);
  rect(ctx, 153, 6, 15, 20, PAL.woodDark);
  rect(ctx, 154, 7, 13, 8, PAL.wood);
  rect(ctx, 154, 17, 13, 8, PAL.wood);
  rect(ctx, 165, 15, 1, 2, PAL.yellow);
}

function drawFloor(ctx, color) {
  for (let y = 26; y < ROOM_H; y += 6) {
    rect(ctx, 0, y, ROOM_W, 6, (y / 6) % 2 ? "#6b4636" : "#644031");
    rect(ctx, 0, y + 5, ROOM_W, 1, "#4a3226");
    const off = ((y / 6) % 3) * 23;
    for (let x = off; x < ROOM_W; x += 69) rect(ctx, x, y, 1, 5, "#4a3226");
  }
  // Ковёр в зоне отдыха — цвета отдела
  const rug = mix(color, "#2a2240", 0.55);
  rect(ctx, 40, 31, 100, 14, shade(rug, -30));
  rect(ctx, 41, 32, 98, 12, rug);
  for (let x = 44; x < 138; x += 6) rect(ctx, x, 37, 3, 1, shade(rug, 25));
}

function drawLounge(ctx, color) {
  // Диван
  const sofa = mix(color, "#3b2f52", 0.5);
  rect(ctx, 6, 30, 30, 14, PAL.outline);
  rect(ctx, 7, 31, 28, 6, shade(sofa, -15));
  rect(ctx, 7, 37, 28, 6, sofa);
  rect(ctx, 7, 31, 3, 12, shade(sofa, -30));
  rect(ctx, 32, 31, 3, 12, shade(sofa, -30));
  // Кулер
  rect(ctx, 145, 27, 9, 18, PAL.outline);
  rect(ctx, 146, 28, 7, 6, "#7fd3ff");
  rect(ctx, 146, 34, 7, 10, "#e9e4f2");
  rect(ctx, 148, 37, 3, 1, PAL.blue);
  // Растение
  rect(ctx, 160, 36, 7, 8, PAL.outline);
  rect(ctx, 161, 37, 5, 6, PAL.pot);
  rect(ctx, 158, 28, 11, 8, PAL.plant);
  rect(ctx, 160, 26, 7, 3, PAL.plantLight);
}

function drawDeskFront(ctx, x0, mood, look, frame, accent) {
  // Монитор
  rect(ctx, x0 + 2, 50, 13, 11, PAL.outline);
  rect(ctx, x0 + 3, 51, 11, 9, PAL.metal);
  const on = mood === "working" || mood === "waiting";
  rect(ctx, x0 + 4, 52, 9, 7, on ? PAL.screenBg : PAL.screenOff);
  if (mood === "working") {
    for (let i = 0; i < 3; i++) rect(ctx, x0 + 5, 53 + i * 2, 2 + ((hash(x0 + "" + (i + frame)) >>> 3) % 6), 1, i % 2 ? accent : shade(accent, 60));
  } else if (mood === "waiting") {
    if (frame % 2) {
      rect(ctx, x0 + 8, 53, 1, 3, PAL.yellow);
      rect(ctx, x0 + 8, 57, 1, 1, PAL.yellow);
    }
  } else {
    rect(ctx, x0 + 5, 53, 2, 1, shade(PAL.screenOff, 30));
  }
  rect(ctx, x0 + 7, 61, 3, 1, PAL.outline);
  // Стол
  rect(ctx, x0, DESK_TOP, 36, 14, PAL.outline);
  rect(ctx, x0 + 1, DESK_TOP + 1, 34, 2, PAL.woodLight);
  rect(ctx, x0 + 1, DESK_TOP + 3, 34, 10, PAL.wood);
  rect(ctx, x0 + 1, DESK_TOP + 3, 34, 1, PAL.woodDark);
  rect(ctx, x0 + 4, DESK_TOP + 6, 10, 4, PAL.woodDark);
  rect(ctx, x0 + 8, DESK_TOP + 8, 2, 1, PAL.woodLight);
  // Клавиатура
  rect(ctx, x0 + 16, DESK_TOP - 1, 11, 2, PAL.outline);
  rect(ctx, x0 + 17, DESK_TOP - 1, 9, 1, PAL.key);
  // Кружка
  rect(ctx, x0 + 29, 58, 4, 4, PAL.outline);
  rect(ctx, x0 + 30, 59, 2, 2, PAL.mug);
  if (mood === "working" && frame % 3 === 0) rect(ctx, x0 + 30, 55 - (frame % 2), 1, 2, "#d9d4e8");
  // Руки на клавиатуре
  if (look && mood === "working") {
    const a = frame % 2 ? -1 : 0, b = frame % 2 ? 0 : -1;
    rect(ctx, x0 + 17, DESK_TOP - 2 + a, 2, 2, look.skin);
    rect(ctx, x0 + 24, DESK_TOP - 2 + b, 2, 2, look.skin);
  }
}

// members: [{ id, color, x, y, seated, walking, mood, bubble, deskIndex }]
export function drawRoom(canvas, { color, members, runs, sky, frame }) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const layout = roomLayout(members.length);

  drawWall(ctx, color, sky, runs, frame);
  drawFloor(ctx, color);
  drawLounge(ctx, color);

  // Спинки кресел
  for (const x0 of layout.desks) {
    rect(ctx, x0 + 14, 54, 12, 9, PAL.outline);
    rect(ctx, x0 + 15, 55, 10, 8, PAL.chair);
    rect(ctx, x0 + 15, 55, 10, 1, PAL.chairLight);
  }

  // Сотрудники: дальние (выше по экрану) рисуются раньше
  const looks = new Map(members.map((m) => [m.id, lookFor(m)]));
  [...members].sort((a, b) => a.y - b.y).forEach((m) => {
    const look = looks.get(m.id);
    const bob = !m.walking && !m.seated && (frame + (hash(m.id) % 7)) % 14 === 0 ? -1 : 0;
    drawCharacter(ctx, look, m.x, m.y + bob, {
      standing: !m.seated,
      step: m.walking ? frame : 0,
      eyesClosed: m.mood === "idle" && (frame + (hash(m.id) % 11)) % 20 > 17,
    });
    if (m.mood === "waiting" && m.seated) {
      const up = frame % 2;
      rect(ctx, m.x + 10, m.y - 3 + up, 3, 10, PAL.outline);
      rect(ctx, m.x + 11, m.y + 1 + up, 1, 5, look.shirt);
      rect(ctx, m.x + 11, m.y - 2 + up, 1, 3, look.skin);
    }
  });

  // Столы поверх ног — так персонаж «садится» за стол
  layout.desks.forEach((x0, i) => {
    const m = members.find((mm) => mm.deskIndex === i);
    const seatedHere = m && m.seated;
    drawDeskFront(ctx, x0, seatedHere ? m.mood : "idle", seatedHere ? looks.get(m.id) : null, frame, color);
  });

  // Пузыри над головами
  for (const m of members) {
    if (m.bubble) bubble(ctx, m.x + 5, m.y - (lookFor(m).style === "bun" ? 2 : 0), m.bubble, frame);
  }
}

// ---------- Портрет 12×12 для чата и списков ----------

const portraitCache = new Map();

export function portrait(member) {
  const look = lookFor(member);
  const key = `${member.id}|${look.shirt}`;
  if (portraitCache.has(key)) return portraitCache.get(key);
  const c = document.createElement("canvas");
  c.width = 12;
  c.height = 12;
  const ctx = c.getContext("2d");
  rect(ctx, 0, 0, 12, 12, mix(look.shirt, "#17121f", 0.65));
  drawCharacter(ctx, look, 1, look.style === "bun" ? 2 : 1);
  const url = c.toDataURL();
  portraitCache.set(key, url);
  return url;
}

// ---------- Иконки 10×10 ----------

const ICONS = {
  office: [".oooooooo.", ".owywwywo.", ".owwwwwwo.", ".owywwywo.", ".owwwwwwo.", ".owywwywo.", ".owwddwwo.", ".owwddwwo.", "oooooooooo", ".........."],
  panel: ["oooooooooo", "okkkkkkkko", "okgkkkrkko", "okkkkkkkko", "oooooooooo", "owwwwwwwwo", "owyowyowyo", "owwwwwwwwo", "oooooooooo", ".........."],
  chat: [".oooooooo.", "owwwwwwwwo", "owwwwwwwwo", "owkwkwkwwo", "owwwwwwwwo", "owwwwwwwwo", ".ooowoooo.", "...owo....", "...oo.....", ".........."],
  tasks: ["...oooo...", ".oooyyooo.", ".owwwwwwo.", ".owkkkkwo.", ".owwwwwwo.", ".owkkkwwo.", ".owwwwwwo.", ".owkkkkwo.", ".owwwwwwo.", ".oooooooo."],
  files: ["ooooooooo.", "obllldllbo", "obllldllbo", "obbbbbbbbo", "obbbbbbbbo", "obwwwwwwbo", "obwkkkkwbo", "obwwwwwwbo", "obwwwwwwbo", "oooooooooo"],
  team: ["...oooo...", "..osssso..", "..osesso..", "..osssso..", "...oooo...", ".oooooooo.", "occcccccco", "occcccccco", "occcccccco", "oooooooooo"],
  bell: ["....oo....", "...oyyo...", "..oyyyyo..", "..oyyyyo..", ".oyyyyyyo.", ".oyyyyyyo.", "oyyyyyyyyo", "oooooooooo", "....oo....", ".........."],
  fire: ["....o.....", "...oro....", "...orro...", "..oryro...", ".oryyyro..", ".oryyyyro.", ".oryyyyro.", "..oryyro..", "...oooo...", ".........."],
  star: ["....oo....", "...oyyo...", "oooyyyyooo", "oyyyyyyyyo", ".oyyyyyyo.", "..oyyyyo..", ".oyyooyyo.", ".oyo..oyo.", ".oo....oo.", ".........."],
  bolt: [".....ooo..", "....oyyo..", "...oyyo...", "..oyyyooo.", ".oyyyyyyo.", "..ooyyyo..", "...oyyo...", "..oyyo....", "..ooo.....", ".........."],
  plus: ["...oooo...", "...owwo...", "...owwo...", "oooowwoooo", "owwwwwwwwo", "owwwwwwwwo", "oooowwoooo", "...owwo...", "...owwo...", "...oooo..."],
};

const ICON_COLORS = {
  o: PAL.outline,
  w: "#fff1e8",
  y: "#ffd23f",
  r: "#ff6b3d",
  d: "#a0603a",
  k: "#5f5a6e",
  b: "#3a6cff",
  l: "#c2c3c7",
  s: "#ffd1aa",
  e: PAL.ink,
  c: "#ff6b8b",
  g: "#5fd07e",
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

// Иконка отдела: рамка его цвета с первой буквой-«пиктограммой» — квадрат 10×10.
export function groupIcon(group) {
  const key = `g|${group.id}|${group.color}`;
  if (iconCache.has(key)) return iconCache.get(key);
  const c = document.createElement("canvas");
  c.width = 10;
  c.height = 10;
  const ctx = c.getContext("2d");
  rect(ctx, 0, 0, 10, 10, PAL.outline);
  rect(ctx, 1, 1, 8, 8, group.color);
  rect(ctx, 1, 1, 8, 1, shade(group.color, 50));
  rect(ctx, 1, 8, 8, 1, shade(group.color, -50));
  // Маленький «человечек» в центре — символ команды
  rect(ctx, 4, 2, 2, 2, PAL.outline);
  rect(ctx, 3, 5, 4, 3, PAL.outline);
  const url = c.toDataURL();
  iconCache.set(key, url);
  return url;
}
