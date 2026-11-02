"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SquarePen, Trash2 } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { chatKeys, deleteChat, listChats } from "@/lib/api/chat";
import { cn, notAfter } from "@/lib/utils";

import { useChatTitle } from "./chat-title";

/** Opens an empty chat; the server gets a chat only with its first message. */
export function NewChatButton({ className }: { className?: string }) {
  const t = useTranslations("chat");
  return (
    <Button asChild className={cn("w-full", className)}>
      <Link href="/chat/new">
        <SquarePen /> {t("newChat")}
      </Link>
    </Button>
  );
}

/**
 * The owner's chats, newest first. `sidebar`: compact titles in the desktop sidebar (like
 * Claude's "Recents"); `page`: the phone's chat page, with the time of the last message.
 */
export function ChatList({ variant, className }: { variant: "sidebar" | "page"; className?: string }) {
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
      if (pathname === `/chat/${id}`) router.push("/chat/new");
    },
  });
  const compact = variant === "sidebar";

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {remove.error && (
        <p role="alert" className="px-2 pb-2 text-xs text-destructive">
          {toMessage(remove.error).message}
        </p>
      )}
      <nav aria-label={t("history")} className="flex flex-col gap-0.5">
        {chats.isPending && <p className="px-3 py-2 text-sm text-muted-foreground">{tc("loading")}</p>}
        {chats.isError && !chats.data && (
          <div role="alert" className="flex flex-col items-start gap-2 px-3 py-2 text-sm">
            <p>{toMessage(chats.error).message}</p>
            <Button variant="outline" size="sm" onClick={() => chats.refetch()}>
              {tc("retry")}
            </Button>
          </div>
        )}
        {chats.data?.items.length === 0 && <p className="px-3 py-2 text-sm text-muted-foreground">{t("noChats")}</p>}
        {chats.data?.items.map((chat) => {
          const active = pathname === `/chat/${chat.id}`;
          const title = chatTitle(chat.title);
          const when = format.relativeTime(notAfter(new Date(chat.last_message_at), now), now);
          return (
            <div
              key={chat.id}
              className={cn(
                "group flex items-center rounded-lg",
                active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
              )}
            >
              <Link
                href={`/chat/${chat.id}`}
                aria-current={active ? "page" : undefined}
                title={compact ? `${title} · ${when}` : undefined}
                className={cn("flex min-w-0 flex-1 flex-col", compact ? "px-3 py-1.5" : "px-3 py-2.5")}
              >
                <span className="truncate text-sm">{title}</span>
                {!compact && <span className="truncate text-xs text-muted-foreground">{when}</span>}
              </Link>
              <button
                type="button"
                aria-label={t("deleteChat", { title })}
                // Hidden until hover only where there is hover: touch screens always see it.
                className={cn(
                  "flex shrink-0 items-center justify-center rounded-md text-muted-foreground hover:text-destructive focus:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100",
                  compact ? "size-8" : "size-10",
                )}
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
