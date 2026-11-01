"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu, Search, WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ConfirmProvider } from "@/components/ui/confirm";
import { Dialog } from "@/components/ui/dialog";
import { ApprovalsBadge, usePendingApprovalCount } from "@/features/approvals/approvals-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { PixelCow, WalkingCow } from "@/features/mascot/pixel-cow";
import { Notifier } from "@/features/notifications/notifier";
import { RegisterServiceWorker } from "@/features/notifications/register-sw";
import { LocaleSwitcher } from "@/features/preferences/locale-switcher";
import { ThemeSwitcher, ThemeToggle } from "@/features/preferences/theme-toggle";
import { NewTaskDialog } from "@/features/runs/new-task-dialog";
import { authKeys, getMe, logout } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { ConnectionDot, RealtimeProvider } from "@/lib/realtime/provider";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { NAV_GROUPS, PHONE_MORE, PHONE_TABS, type NavItem } from "./nav-items";

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
  const [more, setMore] = useState(false);

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
        <span>{t("common.loading")}</span>
      </div>
    );
  }

  // Only when we never got the account: a failed background refetch keeps the page (and its unsaved input).
  if (!me.data) {
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
  const signOutButton = (
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
  );

  return (
    <RealtimeProvider>
    <ConfirmProvider>
    <a
      href="#main"
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
    >
      {t("nav.skipToContent")}
    </a>
    <div className="flex min-h-dvh">
      {/* Desktop / tablet sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-16 items-center justify-between gap-2 px-4">
          <Link href="/chat" aria-label="moloko">
            <Logo />
          </Link>
        </div>
        <div className="px-2 pt-1">
          <Button className="w-full justify-start gap-2" onClick={() => setNewTask(true)} data-testid="new-task-sidebar">
            <PixelCow mood="happy" size={22} outfit={false} />
            {t("newTask.button")}
          </Button>
        </div>
        <nav aria-label={t("nav.label")} className="flex flex-1 flex-col gap-4 overflow-y-auto px-2 py-3">
          {NAV_GROUPS.map((group) => (
            <div key={group.key} className="flex flex-col gap-0.5">
              <p className="px-3 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {t(`nav.groups.${group.key}`)}
              </p>
              {group.items.map((item) => (
                <SidebarLink key={item.href} item={item} active={isActive(pathname, item.href)} />
              ))}
            </div>
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
              {signOutButton}
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Phone top bar: brand, what needs you, search. Everything else lives under "More". */}
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b bg-card/95 px-4 backdrop-blur md:hidden">
          <Link href="/chat" aria-label="moloko">
            <Logo size="sm" />
          </Link>
          <div className="flex items-center gap-1">
            <ApprovalsBadge />
            <Button variant="ghost" size="icon" asChild>
              <Link href="/search" aria-label={t("nav.search")}>
                <Search />
              </Link>
            </Button>
          </div>
        </header>

        <ConnectionBanner />

        <main
          id="main"
          tabIndex={-1}
          className="flex-1 px-4 pt-6 pb-[calc(6rem+env(safe-area-inset-bottom))] outline-none md:px-8 md:pb-8"
        >
          {children}
        </main>

        {/* Phone tab bar: three sections, the cow "new task" button in the middle, and "More". */}
        <nav
          aria-label={t("nav.label")}
          className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-5 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
          <TabLink item={PHONE_TABS[0]} active={isActive(pathname, PHONE_TABS[0].href)} />
          <TabLink item={PHONE_TABS[1]} active={isActive(pathname, PHONE_TABS[1].href)} />
          <button
            type="button"
            onClick={() => setNewTask(true)}
            data-testid="new-task-cow"
            className="relative flex min-h-14 flex-col items-center justify-end gap-0.5 px-1 pb-2 text-[11px] leading-tight font-medium"
          >
            <span className="-mt-5 flex size-12 items-center justify-center rounded-full border-2 border-[#1b1b2e] bg-[#10142b] shadow-md active:scale-95">
              <PixelCow mood="happy" size={36} />
            </span>
            <span>{t("newTask.button")}</span>
          </button>
          <TabLink item={PHONE_TABS[2]} active={isActive(pathname, PHONE_TABS[2].href)} />
          <MoreTab
            open={more}
            onOpen={() => setMore(true)}
            active={PHONE_MORE.some((item) => isActive(pathname, item.href))}
          />
        </nav>
      </div>
    </div>
    <Dialog open={more} onClose={() => setMore(false)} variant="sheet" labelledBy="more-title" data-testid="more-sheet">
      <div className="flex max-h-[80dvh] flex-col gap-4 overflow-y-auto p-4">
        <div className="flex items-center justify-between gap-2">
          <p id="more-title" className="font-pixel text-lg">
            {t("nav.more")}
          </p>
          <ConnectionStatus />
        </div>
        <nav aria-label={t("nav.moreLabel")} className="flex flex-col gap-1">
          {PHONE_MORE.map((item) => (
            <SheetLink key={item.href} item={item} active={isActive(pathname, item.href)} onNavigate={() => setMore(false)} />
          ))}
        </nav>
        <div className="flex flex-col gap-2">
          <p className="text-xs font-medium text-muted-foreground">{t("preferences.theme")}</p>
          <ThemeSwitcher />
          <p className="pt-1 text-xs font-medium text-muted-foreground">{t("preferences.language")}</p>
          <LocaleSwitcher wide />
        </div>
        <div className="flex items-center justify-between gap-2 border-t pt-3">
          <p className="truncate text-sm text-muted-foreground" title={user.username}>
            {t("auth.signedInAs", { name: displayName })}
          </p>
          <Button variant="outline" onClick={() => signOut.mutate()} disabled={signOut.isPending}>
            <LogOut /> {t("auth.logout")}
          </Button>
        </div>
      </div>
    </Dialog>
    <NewTaskDialog open={newTask} onClose={() => setNewTask(false)} />
    <Notifier />
    <RegisterServiceWorker />
    </ConfirmProvider>
    </RealtimeProvider>
  );
}

function SidebarLink({ item, active }: { item: NavItem; active: boolean }) {
  const t = useTranslations("nav");
  const pending = usePendingApprovalCount();
  const Icon = item.icon;
  const count = item.labelKey === "approvals" ? pending : 0;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      title={t(`hints.${item.labelKey}`)}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
      )}
    >
      <Icon className="size-4" />
      <span className="flex-1">{t(item.labelKey)}</span>
      {count > 0 && (
        <>
          <span className="sr-only">{t("pendingCount", { count })}</span>
          <span
            aria-hidden
            className="rounded-full bg-amber-400 px-1.5 text-xs leading-5 font-semibold text-amber-950"
            data-testid="approvals-badge"
          >
            {count}
          </span>
        </>
      )}
    </Link>
  );
}

function TabLink({ item, active }: { item: NavItem; active: boolean }) {
  const t = useTranslations("nav");
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-label={t(item.labelKey)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-14 flex-col items-center justify-center gap-1 px-1 py-2 text-[11px] leading-tight",
        active ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      <Icon className="size-5" />
      <span className="line-clamp-1 text-center" aria-hidden="true">
        {t(item.shortLabelKey ?? item.labelKey)}
      </span>
    </Link>
  );
}

function MoreTab({ open, onOpen, active }: { open: boolean; onOpen: () => void; active: boolean }) {
  const t = useTranslations("nav");
  const pending = usePendingApprovalCount();
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-haspopup="dialog"
      aria-expanded={open}
      data-testid="more-tab"
      className={cn(
        "relative flex min-h-14 flex-col items-center justify-center gap-1 px-1 py-2 text-[11px] leading-tight",
        active ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      <Menu className="size-5" aria-hidden />
      <span>{t("more")}</span>
      {pending > 0 && (
        <span className="absolute top-1.5 right-[calc(50%-1.1rem)] size-2.5 rounded-full bg-amber-400 ring-2 ring-card">
          <span className="sr-only">{t("pendingCount", { count: pending })}</span>
        </span>
      )}
    </button>
  );
}

function SheetLink({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate: () => void }) {
  const t = useTranslations("nav");
  const pending = usePendingApprovalCount();
  const Icon = item.icon;
  const count = item.labelKey === "approvals" ? pending : 0;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
        active ? "bg-accent text-accent-foreground" : "hover:bg-accent/60",
      )}
    >
      <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-medium">{t(item.labelKey)}</span>
        <span className="truncate text-xs text-muted-foreground">{t(`hints.${item.labelKey}`)}</span>
      </span>
      {count > 0 && (
        <span className="rounded-full bg-amber-400 px-2 text-xs leading-5 font-semibold text-amber-950">
          {count}
          <span className="sr-only"> — {t("pendingCount", { count })}</span>
        </span>
      )}
    </Link>
  );
}

function ConnectionStatus() {
  const t = useTranslations("realtime");
  const status = useRealtimeStore((s) => s.status);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="status" title={t(status)}>
      <ConnectionDot />
      <span>{t(status)}</span>
    </span>
  );
}

/**
 * Says in words when the live connection is down, so a stale screen is never a mystery.
 * Waits a few seconds first: every page load and phone wake-up briefly reconnects.
 */
function ConnectionBanner() {
  const t = useTranslations("realtime");
  const status = useRealtimeStore((s) => s.status);
  const [lasting, setLasting] = useState<typeof status | null>(null); // a status that has lasted 4 s
  useEffect(() => {
    if (status === "online") return;
    const timer = setTimeout(() => setLasting(status), 4000);
    return () => clearTimeout(timer);
  }, [status]);
  if (status === "online" || lasting !== status) return null;
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-400/40 bg-amber-400/15 px-4 py-2 text-sm text-amber-900 md:px-8 dark:text-amber-100"
    >
      <WifiOff className="size-4 shrink-0" aria-hidden />
      <span>{t("banner")}</span>
    </div>
  );
}
