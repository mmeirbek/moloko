import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ChatList, NewChatButton } from "@/features/chat/chat-list";
import { NewChat } from "@/features/chat/new-chat";
import { GettingStarted } from "@/features/onboarding/getting-started";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.chat");
  return { title: t("title") };
}

export default async function ChatIndexPage() {
  return (
    <>
      {/* Phones: the list is the page (first steps above it). Wider screens: the list is in the sidebar, this is a new chat. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto md:hidden">
        <GettingStarted />
        <NewChatButton />
        <ChatList variant="page" />
      </div>
      <div className="hidden min-h-0 flex-1 flex-col md:flex">
        <NewChat />
      </div>
    </>
  );
}
