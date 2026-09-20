import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/src/auth";
import type { PendingSubmission } from "@/src/knowledge-agent/state/submission";
import {
  clearDialogueWork,
  clearDialogueIdentityStorage,
  readDialogueWork,
  readLastDialogueScope,
  writeDialogueWork,
  writeLastDialogueScope,
  type DialogueIdentity,
} from "@/src/knowledge-agent/session/workStorage";
import type { KnowledgeScopeChangeRequest } from "@/src/knowledge-agent/types";

export type ConversationChoice = number | "draft";
export type PendingClientState =
  | "in_flight"
  | "result_unknown"
  | "creation_unknown"
  | null;

interface RecoveryRunRef {
  conversationId: number;
  runId: number;
}

interface DialogueRuntimeState {
  choice: ConversationChoice;
  scope: KnowledgeScopeChangeRequest;
  input: string;
  pending: PendingSubmission | null;
  pendingState: PendingClientState;
  recoveryRun: RecoveryRunRef | null;
}

export interface DialogueSessionValue extends DialogueRuntimeState {
  bootStatus: "idle" | "loading" | "ready" | "error";
  bootError: string | null;
  persistenceError: string | null;
  update: (patch: Partial<DialogueRuntimeState>) => void;
  retryBootstrap: () => void;
  retryPersistence: () => void;
  exitRecovery: () => Promise<void>;
  getReadingPosition: (conversationKey: string) => number | null;
  setReadingPosition: (conversationKey: string, offsetY: number) => void;
  clearReadingPosition: (conversationKey: string) => void;
}

const DEFAULT_SCOPE: KnowledgeScopeChangeRequest = {
  scopeType: "workspace",
  projectId: null,
};

const DEFAULT_RUNTIME: DialogueRuntimeState = {
  choice: "draft",
  scope: DEFAULT_SCOPE,
  input: "",
  pending: null,
  pendingState: null,
  recoveryRun: null,
};

const DialogueSessionContext = createContext<DialogueSessionValue | null>(null);

function identityOf(me: ReturnType<typeof useAuth>["me"]): DialogueIdentity | null {
  if (!me) return null;
  return { userId: me.user.id, workspaceId: me.workspace.id };
}

function hasWork(state: DialogueRuntimeState): boolean {
  return Boolean(state.input.trim() || state.pending || state.recoveryRun);
}

export function DialogueSessionProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const identity = useMemo(() => identityOf(me), [me]);
  const identityKey = identity ? `${identity.userId}:${identity.workspaceId}` : null;
  const [runtime, setRuntime] = useState<DialogueRuntimeState>(DEFAULT_RUNTIME);
  const [bootStatus, setBootStatus] = useState<DialogueSessionValue["bootStatus"]>("idle");
  const [bootError, setBootError] = useState<string | null>(null);
  const [persistenceError, setPersistenceError] = useState<string | null>(null);
  const [loadedIdentityKey, setLoadedIdentityKey] = useState<string | null>(null);
  const [bootstrapGeneration, setBootstrapGeneration] = useState(0);
  const [persistenceGeneration, setPersistenceGeneration] = useState(0);
  const saveQueueRef = useRef(Promise.resolve());
  const persistenceErrorRef = useRef<string | null>(null);
  const readingPositionsRef = useRef(new Map<string, number>());
  const previousIdentityRef = useRef<DialogueIdentity | null>(null);

  useEffect(() => {
    let cancelled = false;
    readingPositionsRef.current.clear();
    const previousIdentity = previousIdentityRef.current;
    const previousKey = previousIdentity
      ? `${previousIdentity.userId}:${previousIdentity.workspaceId}`
      : null;
    previousIdentityRef.current = identity;
    if (previousIdentity && previousKey !== identityKey) {
      saveQueueRef.current = saveQueueRef.current
        .catch(() => undefined)
        .then(() => clearDialogueIdentityStorage(previousIdentity))
        .catch((error: unknown) => {
          const message =
            error instanceof Error ? error.message : "移动对话身份记录清理失败";
          persistenceErrorRef.current = message;
          setPersistenceError(message);
        });
    }
    if (!identity) {
      queueMicrotask(() => {
        if (cancelled) return;
        setRuntime(DEFAULT_RUNTIME);
        setBootStatus("idle");
        setLoadedIdentityKey(null);
        setBootError(null);
        persistenceErrorRef.current = null;
        setPersistenceError(null);
      });
      return () => {
        cancelled = true;
      };
    }
    void Promise.resolve()
      .then(() => {
        if (cancelled) return null;
        setBootStatus("loading");
        setLoadedIdentityKey(null);
        setBootError(null);
        return Promise.all([readLastDialogueScope(identity), readDialogueWork(identity)]);
      })
      .then((result) => {
        if (!result) return;
        const [lastScope, work] = result;
        if (cancelled) return;
        const scope = work?.scope ?? lastScope ?? DEFAULT_SCOPE;
        setRuntime({
          choice:
            work?.conversationId === null || work?.conversationId === undefined
              ? "draft"
              : work.conversationId,
          scope,
          input: work?.input ?? "",
          pending: work?.pending ?? null,
          pendingState: work?.pending
            ? work.pending.conversationId === null
              ? "creation_unknown"
              : "result_unknown"
            : null,
          recoveryRun:
            work?.conversationId != null && work.runId != null
              ? { conversationId: work.conversationId, runId: work.runId }
              : null,
        });
        setLoadedIdentityKey(identityKey);
        setBootStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setBootError(error instanceof Error ? error.message : "移动对话恢复记录读取失败");
        setLoadedIdentityKey(null);
        setBootStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [bootstrapGeneration, identity, identityKey]);

  useEffect(() => {
    if (!identity || bootStatus !== "ready" || loadedIdentityKey !== identityKey) return;
    const snapshot = runtime;
    const delay = snapshot.pending || snapshot.recoveryRun ? 0 : 180;
    const timer = setTimeout(() => {
      saveQueueRef.current = saveQueueRef.current
        .catch(() => undefined)
        .then(async () => {
          await writeLastDialogueScope(identity, snapshot.scope);
          if (hasWork(snapshot)) {
            await writeDialogueWork(identity, {
              version: 1,
              conversationId:
                snapshot.choice === "draft" ? null : snapshot.choice,
              runId: snapshot.recoveryRun?.runId ?? null,
              scope: snapshot.scope,
              input: snapshot.input,
              pending: snapshot.pending,
              updatedAt: new Date().toISOString(),
            });
          } else {
            await clearDialogueWork(identity);
          }
        })
        .then(() => {
          if (persistenceErrorRef.current !== null) {
            persistenceErrorRef.current = null;
            setPersistenceError(null);
          }
        })
        .catch((error: unknown) => {
          const message =
            error instanceof Error ? error.message : "移动对话工作状态保存失败";
          persistenceErrorRef.current = message;
          setPersistenceError(message);
        });
    }, delay);
    return () => clearTimeout(timer);
  }, [
    bootStatus,
    identity,
    identityKey,
    loadedIdentityKey,
    persistenceGeneration,
    runtime,
  ]);

  const update = useCallback((patch: Partial<DialogueRuntimeState>) => {
    setRuntime((previous) => ({ ...previous, ...patch }));
  }, []);

  const exitRecovery = useCallback(async () => {
    if (identity) await clearDialogueWork(identity);
    setRuntime((previous) => ({
      ...DEFAULT_RUNTIME,
      scope: previous.scope,
    }));
    setBootError(null);
    persistenceErrorRef.current = null;
    setPersistenceError(null);
    setBootStatus(identity ? "ready" : "idle");
  }, [identity]);

  const getReadingPosition = useCallback(
    (conversationKey: string) => readingPositionsRef.current.get(conversationKey) ?? null,
    [],
  );
  const setReadingPosition = useCallback((conversationKey: string, offsetY: number) => {
    readingPositionsRef.current.set(conversationKey, Math.max(0, offsetY));
  }, []);
  const clearReadingPosition = useCallback((conversationKey: string) => {
    readingPositionsRef.current.delete(conversationKey);
  }, []);

  const value = useMemo<DialogueSessionValue>(
    () => ({
      ...runtime,
      bootStatus,
      bootError,
      persistenceError,
      update,
      retryBootstrap: () => setBootstrapGeneration((value) => value + 1),
      retryPersistence: () => setPersistenceGeneration((value) => value + 1),
      exitRecovery,
      getReadingPosition,
      setReadingPosition,
      clearReadingPosition,
    }),
    [
      bootError,
      bootStatus,
      clearReadingPosition,
      exitRecovery,
      getReadingPosition,
      persistenceError,
      runtime,
      setReadingPosition,
      update,
    ],
  );

  return (
    <DialogueSessionContext.Provider value={value}>
      {children}
    </DialogueSessionContext.Provider>
  );
}

export function useDialogueSession(): DialogueSessionValue {
  const value = useContext(DialogueSessionContext);
  if (!value) throw new Error("移动对话会话上下文不可用");
  return value;
}
