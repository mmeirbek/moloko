import type { ReactNode } from "react";

/** The chat fills the screen; its list lives in the sidebar (phones: the /chat page). */
export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <section className="-mt-2 flex h-[calc(100dvh-10.5rem)] min-w-0 flex-col md:h-[calc(100dvh-5.5rem)]">{children}</section>
  );
}
