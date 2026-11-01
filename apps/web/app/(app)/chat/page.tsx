import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ChatList } from "@/features/chat/chat-list";
import { PixelCow } from "@/features/mascot/pixel-cow";
import { GettingStarted } from "@/features/onboarding/getting-started";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.chat");
  return { title: t("title") };
}

export default async function ChatIndexPage() {
  const t = await getTranslations("chat");
  return (
    <>
      {/* Phones: the list is the page (first steps above it). Wider screens: the list sits on the left. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4 md:hidden">
        <GettingStarted />
        <ChatList className="min-h-0 flex-1" />
      </div>
      <div className="hidden min-h-0 flex-1 flex-col items-center justify-center gap-6 overflow-y-auto py-6 md:flex">
        <GettingStarted className="w-full max-w-lg" />
        <div className="flex flex-col items-center gap-2 text-center text-sm text-muted-foreground">
          <PixelCow mood="happy" size={56} interactive />
          <p>{t("pick")}</p>
        </div>
      </div>
    </>
  );
}
