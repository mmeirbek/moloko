"use client";

import { Loader2, Mic, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { transcribeAudio } from "@/lib/api/chat";
import { cn } from "@/lib/utils";

const MAX_SECONDS = 120;
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

const noop = () => () => {};
const supported = () =>
  typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

/** Recorder format the browser can make (Safari: mp4, Chrome/Firefox: webm/ogg). */
export function pickType(isSupported: (type: string) => boolean): string | undefined {
  return TYPES.find((type) => isSupported(type));
}

export function extensionFor(type: string): string {
  if (type.includes("mp4")) return "m4a";
  if (type.includes("ogg")) return "ogg";
  return "webm";
}

/**
 * Voice input: press to record, press again (or wait 2 minutes) to stop; the speech is
 * turned into text by the owner's provider and handed to `onText`.
 */
export function MicButton({ onText, className, disabled }: { onText: (text: string) => void; className?: string; disabled?: boolean }) {
  const t = useTranslations("voice");
  const locale = useLocale();
  const toMessage = useErrorMessage();
  const canRecord = useSyncExternalStore(noop, supported, () => false);
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number>(0);

  useEffect(
    () => () => {
      window.clearInterval(timer.current);
      recorder.current?.stream.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  if (!canRecord) return null;

  async function start() {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError(t("denied"));
      return;
    }
    const type = pickType((x) => MediaRecorder.isTypeSupported(x));
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    rec.onstop = async () => {
      window.clearInterval(timer.current);
      stream.getTracks().forEach((track) => track.stop());
      const mime = rec.mimeType || type || "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      if (blob.size === 0) {
        setState("idle");
        return;
      }
      setState("sending");
      try {
        const { text } = await transcribeAudio(blob, `voice.${extensionFor(mime)}`, locale);
        if (text) onText(text);
        else setError(t("nothing"));
      } catch (e) {
        setError(toMessage(e).message);
      } finally {
        setState("idle");
      }
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    const began = Date.now();
    timer.current = window.setInterval(() => {
      const s = Math.floor((Date.now() - began) / 1000);
      setSeconds(s);
      if (s >= MAX_SECONDS && rec.state === "recording") rec.stop();
    }, 250);
  }

  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  const recording = state === "recording";
  return (
    <span className={cn("relative inline-flex items-center", className)}>
      <Button
        type="button"
        size="icon"
        variant={recording ? "destructive" : "ghost"}
        className="rounded-full"
        disabled={disabled || state === "sending"}
        aria-pressed={recording}
        aria-label={recording ? t("stop") : t("start")}
        title={error ?? (recording ? t("stop") : t("start"))}
        onClick={() => (recording ? stop() : void start())}
        data-testid="mic"
      >
        {state === "sending" ? <Loader2 className="animate-spin" /> : recording ? <Square /> : <Mic />}
      </Button>
      {recording && (
        <span className="absolute -top-5 left-1/2 -translate-x-1/2 rounded bg-destructive px-1 text-[10px] text-white tabular-nums" role="status">
          ● {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      )}
      {error && !recording && (
        <span role="alert" className="sr-only">
          {error}
        </span>
      )}
    </span>
  );
}
