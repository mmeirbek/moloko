"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, createChat, deleteChat, listChats } from "@/lib/api/chat";
import { cn } from "@/lib/utils";

import { useChatTitle } from "./chat-title";

export function NewChatButton({ className }: { className?: string }) {
  const t = useTranslations("chat");
  const toMessage = useErrorMessage();
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
    <div className={cn("flex flex-col gap-1", className)}>
      <Button className="w-full" onClick={() => create.mutate()} disabled={create.isPending}>
        <MessageSquarePlus /> {t("newChat")}
      </Button>
      {create.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(create.error).message}
        </p>
      )}
    </div>
  );
}

export function ChatList({ className }: { className?: string }) {
  const t = useTranslations("chat");
  const tc = useTranslations("common");
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const chatTitle = useChatTitle();
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
      {remove.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(remove.error).message}
        </p>
      )}
      <nav aria-label={t("history")} className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {chats.isPending && <p className="px-2 py-4 text-sm text-muted-foreground">{tc("loading")}</p>}
        {chats.isError && !chats.data && (
          <div role="alert" className="flex flex-col items-start gap-2 px-2 py-4 text-sm">
            <p>{toMessage(chats.error).message}</p>
            <Button variant="outline" size="sm" onClick={() => chats.refetch()}>
              {tc("retry")}
            </Button>
          </div>
        )}
        {chats.data?.items.length === 0 && (
          <p className="px-2 py-4 text-sm text-muted-foreground">{t("noChats")}</p>
        )}
        {chats.data?.items.map((chat) => {
          const active = pathname === `/chat/${chat.id}`;
          const title = chatTitle(chat.title);
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
                className="flex min-w-0 flex-1 flex-col px-3 py-2"
              >
                <span className="truncate text-sm">{title}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {format.relativeTime(new Date(chat.last_message_at), now)}
                </span>
              </Link>
              <button
                type="button"
                aria-label={t("deleteChat", { title })}
                // Hidden until hover only where there is hover: touch screens always see it.
                className="flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-destructive focus:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
                disabled={remove.isPending}
                onClick={async () => {
                  if (await confirm({ title: t("confirmDelete"), confirmLabel: tc("delete"), destructive: true }))
                    remove.mutate(chat.id);
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
