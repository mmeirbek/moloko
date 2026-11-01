"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ApprovalsBadge } from "@/features/approvals/approvals-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { PixelCow, WalkingCow } from "@/features/mascot/pixel-cow";
import { Notifier } from "@/features/notifications/notifier";
import { RegisterServiceWorker } from "@/features/notifications/register-sw";
import { LocaleSwitcher } from "@/features/preferences/locale-switcher";
import { ThemeToggle } from "@/features/preferences/theme-toggle";
import { NewTaskDialog } from "@/features/runs/new-task-dialog";
import { authKeys, getMe, logout } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { ConnectionDot, RealtimeProvider } from "@/lib/realtime/provider";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { NAV_ITEMS } from "./nav-items";

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const toMessage = useErrorMessage();
  const [newTask, setNewTask] = useState(false);

  // The backend decides whether we are signed in; the UI only reflects it.
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.isUnauthenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.error, pathname, router]);

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      router.replace("/login");
    },
  });

  if (me.isPending || (me.error instanceof ApiError && me.error.isUnauthenticated)) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
        <WalkingCow size={84} />
        <span className="font-pixel">{t("common.loading")}</span>
      </div>
    );
  }

  if (me.isError) {
    const { message, errorId } = toMessage(me.error);
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center">
        <p role="alert">{message}</p>
        {errorId && <p className="font-mono text-xs text-muted-foreground">{errorId}</p>}
        <Button variant="outline" onClick={() => me.refetch()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  const user = me.data.user;
  const displayName = user.display_name || user.username;

  return (
    <RealtimeProvider>
    <div className="flex min-h-dvh">
      {/* Desktop / tablet sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-16 items-center justify-between gap-2 px-4">
          <Link href="/chat" aria-label="moloko">
            <Logo />
          </Link>
          <ApprovalsBadge />
        </div>
        <div className="px-2 pt-1">
          <Button className="w-full justify-start gap-2" onClick={() => setNewTask(true)} data-testid="new-task-sidebar">
            <PixelCow mood="happy" size={22} outfit={false} />
            {t("newTask.button")}
          </Button>
        </div>
        <nav aria-label={t("nav.label")} className="flex flex-1 flex-col gap-1 px-2 py-2">
          {[...NAV_ITEMS, { href: "/search", labelKey: "search" as const, icon: Search }].map(({ href, labelKey, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive(pathname, href)
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {t(`nav.${labelKey}`)}
            </Link>
          ))}
        </nav>
        <div className="flex flex-col gap-3 border-t p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-xs text-muted-foreground" title={user.username}>
              {t("auth.signedInAs", { name: displayName })}
            </p>
            <ConnectionStatus />
          </div>
          <div className="flex items-center justify-between gap-2">
            <LocaleSwitcher />
            <div className="flex items-center">
              <ThemeToggle />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => signOut.mutate()}
                disabled={signOut.isPending}
                aria-label={t("auth.logout")}
                title={t("auth.logout")}
              >
                <LogOut />
              </Button>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-card/95 px-4 backdrop-blur md:hidden">
          <Link href="/chat" aria-label="moloko">
            <Logo className="[&_svg]:size-7 [&>span:last-child]:text-lg" />
          </Link>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" asChild>
              <Link href="/search" aria-label={t("nav.search")}>
                <Search />
              </Link>
            </Button>
            <ApprovalsBadge />
            <ConnectionStatus />
            <LocaleSwitcher />
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => signOut.mutate()}
              disabled={signOut.isPending}
              aria-label={t("auth.logout")}
            >
              <LogOut />
            </Button>
          </div>
        </header>

        <main className="flex-1 px-4 pt-6 pb-24 md:px-8 md:pb-8">{children}</main>

        {/* Mobile bottom tab bar */}
        <nav
          aria-label={t("nav.label")}
          className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-7 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
          {NAV_ITEMS.map(({ href, labelKey, shortLabelKey, icon: Icon }, index) => (
            <TabSlot key={href} withCow={index === 3} onNewTask={() => setNewTask(true)} label={t("newTask.button")}>
            <Link
              href={href}
              aria-label={t(`nav.${labelKey}`)}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex flex-col items-center gap-1 px-1 py-2 text-[10px] leading-tight",
                isActive(pathname, href) ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <Icon className="size-5" />
              <span className="line-clamp-1 text-center" aria-hidden="true">
                {t(`nav.${shortLabelKey ?? labelKey}`)}
              </span>
            </Link>
            </TabSlot>
          ))}
        </nav>
      </div>
    </div>
    <NewTaskDialog open={newTask} onClose={() => setNewTask(false)} />
    <Notifier />
    <RegisterServiceWorker />
    </RealtimeProvider>
  );
}

function ConnectionStatus() {
  const t = useTranslations("realtime");
  const status = useRealtimeStore((s) => s.status);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status" title={t(status)}>
      <ConnectionDot />
      <span className="sr-only md:not-sr-only">{t(status)}</span>
    </span>
  );
}

/** The cow "new task" button sits in the middle of the phone tab bar, before item `withCow`. */
function TabSlot({
  withCow,
  onNewTask,
  label,
  children,
}: {
  withCow: boolean;
  onNewTask: () => void;
  label: string;
  children: ReactNode;
}) {
  return (
    <>
      {withCow && (
        <button
          type="button"
          onClick={onNewTask}
          aria-label={label}
          data-testid="new-task-cow"
          className="relative flex flex-col items-center justify-end gap-0.5 px-1 pb-2 text-[10px] leading-tight font-medium"
        >
          <span className="-mt-5 flex size-12 items-center justify-center rounded-full border-2 border-[#1b1b2e] bg-[#10142b] shadow-md active:scale-95">
            <PixelCow mood="happy" size={36} />
          </span>
          <span aria-hidden="true">{label}</span>
        </button>
      )}
      {children}
    </>
  );
}
