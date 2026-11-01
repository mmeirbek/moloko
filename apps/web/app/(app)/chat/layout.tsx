import type { ReactNode } from "react";

import { ChatList } from "@/features/chat/chat-list";

export default function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <div className="-mt-2 flex h-[calc(100dvh-10.5rem)] gap-6 md:h-[calc(100dvh-4rem)]">
      <ChatList className="hidden w-64 shrink-0 md:flex" />
      <section className="flex min-w-0 flex-1 flex-col">{children}</section>
    </div>
  );
}
