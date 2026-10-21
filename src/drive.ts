import fs from "node:fs";
import path from "node:path";
import { emit } from "./bus.js";
import { config } from "./config.js";

// Диск офиса — обычная папка. Агенты работают в ней встроенными инструментами Claude Code (Read/Write/Edit),
// а босс видит те же файлы во вкладке «Диск».
export const driveDir = path.join(config.dataDir, "drive");
fs.mkdirSync(driveDir, { recursive: true });

// Возвращает абсолютный путь, только если он внутри диска. Иначе — null.
export function insideDrive(p: string): string | null {
  const abs = path.resolve(driveDir, p);
  const rel = path.relative(driveDir, abs);
  if (rel === "" ) return abs;
  if (rel.startsWith("..") || path.isAbsolute(rel)) return null;
  return abs;
}

function resolveFile(p: string): string {
  const abs = insideDrive(String(p).replace(/\\/g, "/").replace(/^\/+/, ""));
  if (!abs || abs === driveDir) throw new Error("Некорректный путь к файлу");
  return abs;
}

export interface DriveFile {
  path: string;
  size: number;
  updated_at: string;
}

export function listDrive(): DriveFile[] {
  const out: DriveFile[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith(".")) continue;
      const abs = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(abs);
      else if (entry.isFile()) {
        const st = fs.statSync(abs);
        out.push({ path: path.relative(driveDir, abs).split(path.sep).join("/"), size: st.size, updated_at: st.mtime.toISOString() });
      }
    }
  };
  walk(driveDir);
  return out.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function readDrive(p: string) {
  const abs = resolveFile(p);
  if (!fs.existsSync(abs)) return undefined;
  const st = fs.statSync(abs);
  if (st.size > 2_000_000) throw new Error("Файл слишком большой для просмотра");
  return { path: path.relative(driveDir, abs).split(path.sep).join("/"), content: fs.readFileSync(abs, "utf8"), updated_at: st.mtime.toISOString() };
}

export function writeDrive(p: string, content: string) {
  const abs = resolveFile(p);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  fs.writeFileSync(abs, content);
  const rel = path.relative(driveDir, abs).split(path.sep).join("/");
  emit({ type: "file", path: rel });
  return rel;
}

export function deleteDrive(p: string) {
  const abs = resolveFile(p);
  fs.rmSync(abs, { force: true });
  emit({ type: "file", path: p, deleted: true });
}
