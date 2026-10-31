import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ChatList } from "@/features/chat/chat-list";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.chat");
  return { title: t("title") };
}

export default async function ChatIndexPage() {
  const t = await getTranslations("chat");
  return (
    <>
      {/* Phones: the list is the page. Wider screens: the list sits in the sidebar. */}
      <ChatList className="flex-1 md:hidden" />
      <div className="hidden flex-1 items-center justify-center text-sm text-muted-foreground md:flex">
        {t("pick")}
      </div>
    </>
  );
}
