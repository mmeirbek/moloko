import { ChatThread } from "@/features/chat/chat-thread";

/** One chat. The others are in the work list (phones: «Работа» at the bottom). */
export default async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ChatThread key={id} chatId={id} />;
}
