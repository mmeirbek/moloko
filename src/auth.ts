import crypto from "node:crypto";
import type { NextFunction, Request, Response } from "express";
import { config } from "./config.js";

const COOKIE = "office_session";
const MAX_AGE_MS = 1000 * 60 * 60 * 24 * 90;

// Токен привязан к паролю: сменили APP_PASSWORD — все старые сессии перестали работать.
function sessionToken(): string {
  return crypto.createHmac("sha256", config.sessionSecret).update(`session:${config.password}`).digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function readCookie(req: Request, name: string): string | undefined {
  const header = req.headers.cookie;
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return undefined;
}

export function isAuthed(req: Request): boolean {
  const token = readCookie(req, COOKIE);
  return !!token && safeEqual(token, sessionToken());
}

// Простейшая защита от перебора пароля: не больше 10 попыток в 15 минут с одного IP.
const attempts = new Map<string, { count: number; resetAt: number }>();

export function login(req: Request, res: Response) {
  const ip = req.ip ?? "unknown";
  const now = Date.now();
  const entry = attempts.get(ip);
  if (entry && entry.resetAt > now && entry.count >= 10) {
    return res.status(429).json({ error: "Слишком много попыток. Подождите 15 минут." });
  }
  const password = typeof req.body?.password === "string" ? req.body.password : "";
  if (!safeEqual(password, config.password)) {
    if (!entry || entry.resetAt <= now) attempts.set(ip, { count: 1, resetAt: now + 15 * 60_000 });
    else entry.count++;
    return res.status(401).json({ error: "Неверный пароль" });
  }
  attempts.delete(ip);
  res.cookie(COOKIE, sessionToken(), {
    httpOnly: true,
    sameSite: "lax",
    secure: config.isProd,
    maxAge: MAX_AGE_MS,
    path: "/",
  });
  res.json({ ok: true });
}

export function logout(_req: Request, res: Response) {
  res.clearCookie(COOKIE, { path: "/" });
  res.json({ ok: true });
}

export function requireAuth(req: Request, res: Response, next: NextFunction) {
  if (isAuthed(req)) return next();
  res.status(401).json({ error: "Нужно войти" });
}
