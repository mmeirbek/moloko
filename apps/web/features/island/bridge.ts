/**
 * The contract with the Mac notch app (apps/mac-island), when this page runs in its web view.
 *
 * Page → app, `window.webkit.messageHandlers.molokoIsland.postMessage(...)`:
 * - `{type: "status", pendingApprovals, activeAgents, signedIn}` — what the folded pill shows;
 * - `{type: "approval", id, summary, agent}` — a pending approval not reported yet (as it appears,
 *   and every pending one once after the page loads): the app shows a notification;
 * - `{type: "approvalGone", id}` — a reported approval stopped being pending: the app withdraws it;
 * - `{type: "approvalsPending", ids}` — once per page load, every pending id: the app withdraws
 *   notifications of approvals answered while the page was not running;
 * - `{type: "approvalResolved", id, ok, message}` — the answer to an `action` event below.
 *
 * App → page, the window event `moloko-island` with `detail`:
 * - `{open}` — the panel opened or closed (and once after each load);
 * - `{open: true, focus: "task"}` — opened from the hotkey: put the cursor in the task row;
 * - `{action: "approve" | "reject", approvalId}` — a notification button: answer that approval.
 */

export const ISLAND_EVENT = "moloko-island";

export type IslandMessage =
  | { type: "status"; pendingApprovals: number; activeAgents: number; signedIn: boolean }
  | { type: "approval"; id: string; summary: string; agent: string }
  | { type: "approvalGone"; id: string }
  | { type: "approvalsPending"; ids: string[] }
  | { type: "approvalResolved"; id: string; ok: boolean; message: string };

export type ApprovalAction = { action: "approve" | "reject"; approvalId: string };

type Bridge = { postMessage: (message: unknown) => void };

/** The Mac app's message handler, when this page runs inside it. */
export function nativeBridge(): Bridge | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as { webkit?: { messageHandlers?: { molokoIsland?: Bridge } } }).webkit?.messageHandlers
    ?.molokoIsland;
}

/** Sends a message to the Mac app; a no-op in a browser. */
export function postToNative(message: IslandMessage): void {
  nativeBridge()?.postMessage(message);
}

/** Which reported approvals are new and which are no longer pending. */
export function approvalChanges(
  reported: ReadonlySet<string>,
  pendingIds: readonly string[],
): { added: string[]; gone: string[] } {
  const pending = new Set(pendingIds);
  return {
    added: pendingIds.filter((id) => !reported.has(id)),
    gone: [...reported].filter((id) => !pending.has(id)),
  };
}

/** The approval action in a `moloko-island` event, if it is a well-formed one. */
export function approvalActionOf(detail: unknown): ApprovalAction | null {
  if (!detail || typeof detail !== "object") return null;
  const { action, approvalId } = detail as Record<string, unknown>;
  if (action !== "approve" && action !== "reject") return null;
  if (typeof approvalId !== "string" || approvalId === "") return null;
  return { action, approvalId };
}

/** The field the app asks to focus (`"task"`), if any. */
export function focusRequestOf(detail: unknown): string | null {
  if (!detail || typeof detail !== "object") return null;
  const { focus } = detail as Record<string, unknown>;
  return typeof focus === "string" ? focus : null;
}
