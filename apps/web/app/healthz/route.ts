// Container health check for the frontend (no auth, no backend calls).
export const dynamic = "force-static";

export function GET() {
  return new Response("ok", { headers: { "Content-Type": "text/plain" } });
}
