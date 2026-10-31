import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";
import Link from "next/link";

import { ChatThread } from "@/features/chat/chat-thread";

export default async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await getTranslations("chat");
  return (
    <>
      <Link href="/chat" className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground md:hidden">
        <ArrowLeft className="size-4" /> {t("allChats")}
      </Link>
      <ChatThread key={id} chatId={id} />
    </>
  );
}
