import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { Button, Modal, cn } from "./ui";

type ToastKind = "success" | "error" | "info" | "warning";
interface Toast {
  id: number;
  kind: ToastKind;
  message: ReactNode;
}

interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  checkbox?: string;
}

interface FeedbackApi {
  toast: (message: ReactNode, kind?: ToastKind) => void;
  success: (message: ReactNode) => void;
  error: (error: unknown) => void;
  confirm: (options: ConfirmOptions) => Promise<{ confirmed: boolean; checked: boolean }>;
}

const FeedbackContext = createContext<FeedbackApi | null>(null);

export function useFeedback(): FeedbackApi {
  const ctx = useContext(FeedbackContext);
  if (!ctx) throw new Error("FeedbackProvider missing");
  return ctx;
}

const icons: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="size-5 text-emerald-500" />,
  error: <XCircle className="size-5 text-red-500" />,
  info: <Info className="size-5 text-sky-500" />,
  warning: <AlertTriangle className="size-5 text-amber-500" />,
};

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);
  const [confirmState, setConfirmState] = useState<(ConfirmOptions & { resolve: (r: { confirmed: boolean; checked: boolean }) => void }) | null>(null);
  const [checked, setChecked] = useState(false);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const toast = useCallback(
    (message: ReactNode, kind: ToastKind = "info") => {
      const id = ++counter.current;
      setToasts((all) => [...all.slice(-4), { id, kind, message }]);
      window.setTimeout(() => dismiss(id), kind === "error" ? 7000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<FeedbackApi>(
    () => ({
      toast,
      success: (message) => toast(message, "success"),
      error: (error) => toast(error instanceof Error ? error.message : String(error), "error"),
      confirm: (options) =>
        new Promise((resolve) => {
          setChecked(false);
          setConfirmState({ ...options, resolve });
        }),
    }),
    [toast],
  );

  const closeConfirm = (confirmed: boolean) => {
    confirmState?.resolve({ confirmed, checked });
    setConfirmState(null);
  };

  return (
    <FeedbackContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-2 px-4 sm:top-auto sm:right-4 sm:bottom-24 sm:left-auto sm:items-end">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex w-full max-w-sm animate-slide-up items-start gap-3 rounded-xl border border-zinc-200 bg-white p-3 pr-2 shadow-lg dark:border-zinc-800 dark:bg-zinc-900"
          >
            <span className="mt-0.5 shrink-0">{icons[t.kind]}</span>
            <div className="min-w-0 flex-1 text-sm break-words">{t.message}</div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800"
              aria-label="Dismiss"
            >
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
      <Modal
        open={confirmState !== null}
        onClose={() => closeConfirm(false)}
        title={confirmState?.title ?? ""}
        size="sm"
        footer={
          <>
            <Button onClick={() => closeConfirm(false)}>Cancel</Button>
            <Button variant={confirmState?.danger ? "danger" : "primary"} onClick={() => closeConfirm(true)} autoFocus>
              {confirmState?.confirmLabel ?? "Confirm"}
            </Button>
          </>
        }
      >
        {confirmState?.message && <div className="text-sm text-zinc-600 dark:text-zinc-300">{confirmState.message}</div>}
        {confirmState?.checkbox && (
          <label className={cn("mt-4 flex items-center gap-2 text-sm", "cursor-pointer")}>
            <input type="checkbox" className="size-4 accent-brand-600" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            {confirmState.checkbox}
          </label>
        )}
      </Modal>
    </FeedbackContext.Provider>
  );
}
