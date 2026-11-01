"use client";

import { useTranslations } from "next-intl";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

import { Button } from "./button";
import { Dialog } from "./dialog";

interface ConfirmOptions {
  title: string;
  description?: string;
  /** Label of the confirming button; defaults to "Yes". */
  confirmLabel?: string;
  /** Red confirming button: the action deletes or stops something. */
  destructive?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

/** `const confirm = useConfirm(); if (await confirm({ title })) …` — an in-app replacement for window.confirm. */
export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm needs <ConfirmProvider>");
  return confirm;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const t = useTranslations("common");
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((answer: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>((next) => {
    resolver.current?.(false); // a second question cancels the first
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  function answer(value: boolean) {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  }

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={options !== null} onClose={() => answer(false)} labelledBy="confirm-title" data-testid="confirm-dialog">
        {options && (
          <div className="flex flex-col gap-4 p-5">
            <div className="flex flex-col gap-1.5">
              <p id="confirm-title" className="text-base font-semibold">
                {options.title}
              </p>
              {options.description && <p className="text-sm text-muted-foreground">{options.description}</p>}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={() => answer(false)} autoFocus>
                {t("cancel")}
              </Button>
              <Button variant={options.destructive ? "destructive" : "default"} onClick={() => answer(true)}>
                {options.confirmLabel ?? t("yes")}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </ConfirmContext.Provider>
  );
}
