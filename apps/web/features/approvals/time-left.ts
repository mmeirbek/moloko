/** Whole minutes until ``expiresAt`` (never negative). */
export function minutesLeft(expiresAt: string, now: number = Date.now()): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 60_000));
}
