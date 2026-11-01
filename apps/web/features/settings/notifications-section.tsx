"use client";

import { useLocale, useTranslations } from "next-intl";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { disablePush, enablePush, needsHomeScreen, pushSupported, syncPush } from "@/lib/notifications/push";
import {
  DEFAULT_PREFS,
  prefsSnapshot,
  savePrefs,
  subscribePrefs,
  type NotificationPrefs,
} from "@/lib/notifications/rules";

const noop = () => () => {};
const permissionNow = () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission);
const supportNow = () => (pushSupported() ? (needsHomeScreen() ? "homescreen" : "yes") : "no");

export function NotificationsSection() {
  const t = useTranslations("notifications.settings");
  const prefs = useSyncExternalStore(subscribePrefs, prefsSnapshot, () => DEFAULT_PREFS);
  const browserPermission = useSyncExternalStore(noop, permissionNow, () => "default");
  const [asked, setAsked] = useState<string | null>(null);
  const permission = asked ?? browserPermission;
  const locale = useLocale();
  const pushSupport = useSyncExternalStore(noop, supportNow, () => "no");
  const [pushBusy, setPushBusy] = useState(false);
  const [pushError, setPushError] = useState(false);
  const update = (next: NotificationPrefs) => {
    savePrefs(next);
    void syncPush(next, locale).catch(() => undefined); // the server knows which kinds this device wants
  };
  async function togglePush(on: boolean) {
    setPushBusy(true);
    setPushError(false);
    try {
      if (on) await enablePush(prefs, locale);
      else await disablePush();
      savePrefs({ ...prefs, push: on });
      if (on) setAsked("granted");
    } catch {
      setPushError(true);
    } finally {
      setPushBusy(false);
    }
  }
  async function allowSystem() {
    if (typeof Notification === "undefined") return;
    const result = await Notification.requestPermission();
    setAsked(result);
    update({ ...prefs, system: result === "granted" });
  }
  return (
    <Card id="notifications">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {(["approval", "taskDone", "taskFailed", "budget"] as const).map((kind) => (
          <label key={kind} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs[kind]}
              onChange={(e) => update({ ...prefs, [kind]: e.target.checked })}
            />
            {t(`kinds.${kind}`)}
          </label>
        ))}
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          {permission === "granted" ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.system}
                onChange={(e) => update({ ...prefs, system: e.target.checked })}
              />
              {t("system")}
            </label>
          ) : permission === "unsupported" ? (
            <p className="text-muted-foreground">{t("unsupported")}</p>
          ) : (
            <Button variant="outline" size="sm" onClick={() => void allowSystem()} disabled={permission === "denied"}>
              {permission === "denied" ? t("blocked") : t("allow")}
            </Button>
          )}
        </div>
        <div className="flex flex-col gap-1 border-t pt-3" data-testid="push-settings">
          {pushSupport === "yes" ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.push}
                disabled={pushBusy || permission === "denied"}
                onChange={(e) => void togglePush(e.target.checked)}
              />
              {t("push")}
            </label>
          ) : (
            <p className="text-muted-foreground">
              {pushSupport === "homescreen" ? t("pushHomeScreen") : t("pushUnsupported")}
            </p>
          )}
          <p className="text-xs text-muted-foreground">{t("pushNote")}</p>
          {pushError && (
            <p role="alert" className="text-xs text-destructive">
              {t("pushError")}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
