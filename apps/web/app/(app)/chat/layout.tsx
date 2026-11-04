import type { ReactNode } from "react";

/** The chat fills the screen; the chats and tasks are in the work list (phones: «Работа»).
 *  Phones: the header, the page's padding and the room for the bottom bar — which pads itself
 *  with the iPhone's home-indicator inset — leave exactly this much; without subtracting the
 *  inset the page grew 34 px past the screen and scrolled itself instead of the chat. */
export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <section className="-mt-2 flex h-[calc(100dvh-10.5rem-env(safe-area-inset-bottom))] min-w-0 flex-col md:h-[calc(100dvh-5.5rem)]">{children}</section>
  );
}
