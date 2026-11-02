import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ArrowLeft } from "@/components/icons";
import { NewChat } from "@/features/chat/new-chat";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("chat");
  return { title: t("newChat") };
}

export default async function NewChatPage() {
  const t = await getTranslations("chat");
  return (
    <>
      <Link href="/chat" className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground md:hidden">
        <ArrowLeft className="size-4" /> {t("allChats")}
      </Link>
      <NewChat />
    </>
  );
}
