"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { chatKeys, createChat, deleteChat, listChats } from "@/lib/api/chat";
import { cn } from "@/lib/utils";

export function NewChatButton({ className }: { className?: string }) {
  const t = useTranslations("chat");
  const router = useRouter();
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => createChat(),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      router.push(`/chat/${chat.id}`);
    },
  });
  return (
    <Button className={className} onClick={() => create.mutate()} disabled={create.isPending}>
      <MessageSquarePlus /> {t("newChat")}
    </Button>
  );
}

export function ChatList({ className }: { className?: string }) {
  const t = useTranslations("chat");
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const chats = useQuery({ queryKey: chatKeys.list, queryFn: ({ signal }) => listChats(signal) });
  const remove = useMutation({
    mutationFn: deleteChat,
    onSuccess: (_, id) => {
      void queryClient.invalidateQueries({ queryKey: chatKeys.list });
      if (pathname === `/chat/${id}`) router.push("/chat");
    },
  });

  return (
    <div className={cn("flex min-h-0 flex-col gap-3", className)}>
      <NewChatButton className="w-full" />
      <nav aria-label={t("history")} className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {chats.data?.items.length === 0 && (
          <p className="px-2 py-4 text-sm text-muted-foreground">{t("noChats")}</p>
        )}
        {chats.data?.items.map((chat) => {
          const active = pathname === `/chat/${chat.id}`;
          return (
            <div
              key={chat.id}
              className={cn(
                "group flex items-center gap-1 rounded-md pr-1",
                active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
              )}
            >
              <Link
                href={`/chat/${chat.id}`}
                aria-current={active ? "page" : undefined}
                className="min-w-0 flex-1 truncate px-3 py-2 text-sm"
              >
                {chat.title}
              </Link>
              <button
                type="button"
                aria-label={t("deleteChat", { title: chat.title })}
                className="rounded p-1 text-muted-foreground opacity-60 hover:text-destructive focus:opacity-100 md:opacity-0 md:group-hover:opacity-100"
                onClick={() => {
                  if (window.confirm(t("confirmDelete"))) remove.mutate(chat.id);
                }}
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          );
        })}
      </nav>
    </div>
  );
}
