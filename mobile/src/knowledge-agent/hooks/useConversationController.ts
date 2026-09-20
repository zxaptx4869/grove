import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import {
  classifyKnowledgeAgentError,
  toUserErrorMessage,
} from "@/src/knowledge-agent/errors";
import { useAppStateActive } from "@/src/knowledge-agent/hooks/useAppState";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";
import { useDialogueSession } from "@/src/knowledge-agent/session/DialogueSessionProvider";
import {
  composeThread,
  upsertRun,
  type MessageThreadState,
} from "@/src/knowledge-agent/state/messages";
import {
  DEFAULT_MODES,
  withContextMode,
  type ModeSelection,
} from "@/src/knowledge-agent/state/modes";
import {
  attachConversation,
  canRetrySubmission,
  createPendingSubmission,
  type PendingSubmission,
} from "@/src/knowledge-agent/state/submission";
import type {
  ContextMode,
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
  KnowledgeScopeChangeRequest,
  RunStatus,
} from "@/src/knowledge-agent/types";
import { isRunActive } from "@/src/knowledge-agent/types";

export interface ConversationController {
  initialLoading: boolean;
  conversationsLoading: boolean;
  conversations: KnowledgeConversation[] | undefined;
  conversationsError: string | null;
  activeConversation: KnowledgeConversation | null;
  activeConversationLoading: boolean;
  isDraft: boolean;
  userInitiatedDraft: boolean;
  currentScope: KnowledgeScopeChangeRequest;
  scopeLabel: string;
  scopeBusy: boolean;
  scopeError: string | null;
  changeScope: (scope: KnowledgeScopeChangeRequest) => Promise<void>;
  switchToConversation: (conversationId: number) => void;
  startNewConversation: () => void;
  retryConversations: () => void;
  thread: MessageThreadState;
  messagesLoading: boolean;
  messagesError: string | null;
  loadOlderMessages: () => Promise<void>;
  loadingOlder: boolean;
  olderError: string | null;
  pending: PendingSubmission | null;
  input: string;
  setInput: (value: string) => void;
  submitting: boolean;
  submissionResultUnknown: boolean;
  conversationCreationUnknown: boolean;
  submitError: string | null;
  recoveryError: string | null;
  persistenceError: string | null;
  retryRecovery: () => void;
  retryPersistence: () => void;
  exitRecovery: () => Promise<void>;
  getReadingPosition: (conversationKey: string) => number | null;
  setReadingPosition: (conversationKey: string, offsetY: number) => void;
  clearReadingPosition: (conversationKey: string) => void;
  modes: ModeSelection;
  setContextMode: (mode: ContextMode) => void;
  setModes: (modes: ModeSelection) => void;
  submit: (text: string) => Promise<boolean>;
  continueRun: (runId: number) => Promise<boolean>;
  retrySubmit: () => Promise<boolean>;
  retryRun: (runId: number) => Promise<boolean>;
  resumableRunId: number | null;
  activeRun: KnowledgeRun | null;
  runPolling: boolean;
  runPollingError: string | null;
  retryRunPolling: () => void;
  cancelling: boolean;
  cancelError: string | null;
  requestCancelRun: () => Promise<void>;
  appActive: boolean;
}

interface RunCancelError {
  runId: number;
  message: string;
}

interface ConversationRequestOwner {
  conversationId: number;
  generation: number;
}

interface OlderPageRequest extends ConversationRequestOwner {
  cursor: string;
}

function scopeLabelOf(scope: KnowledgeScopeChangeRequest): string {
  return scope.scopeType === "project" ? scope.projectName ?? "项目" : "全部知识";
}

function sameScope(
  left: KnowledgeScopeChangeRequest,
  right: KnowledgeScopeChangeRequest,
): boolean {
  return (
    left.scopeType === right.scopeType &&
    (left.projectId ?? null) === (right.projectId ?? null)
  );
}

export function useConversationController(
  token: string | null,
): ConversationController {
  const queryClient = useQueryClient();
  const appActive = useAppStateActive();
  const session = useDialogueSession();
  const [olderPages, setOlderPages] = useState<KnowledgeMessagePage[]>([]);
  const [runOverrides, setRunOverrides] = useState<Map<number, KnowledgeRun>>(
    () => new Map(),
  );
  const [extraMessages, setExtraMessages] = useState<KnowledgeMessage[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [modes, setModesState] = useState<ModeSelection>(DEFAULT_MODES);
  const modesRef = useRef(modes);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [cancelError, setCancelError] = useState<RunCancelError | null>(null);
  const previousRunStatusRef = useRef<RunStatus | null>(null);
  const [conversationGeneration, setConversationGeneration] = useState(0);
  const conversationGenerationRef = useRef(0);
  const olderPageRequestRef = useRef<OlderPageRequest | null>(null);
  const submissionRequestRef = useRef(false);
  const pending = session.pending;
  const submissionResultUnknown = session.pendingState === "result_unknown";
  const conversationCreationUnknown = session.pendingState === "creation_unknown";

  useEffect(() => {
    modesRef.current = modes;
  }, [modes]);

  const conversationsQuery = useQuery({
    queryKey: knowledgeAgentKeys.conversations(),
    queryFn: () => knowledgeAgentApi.listConversations(token as string),
    enabled: Boolean(token),
  });
  const conversations = conversationsQuery.data;
  const selectedConversationId =
    session.bootStatus === "ready" && session.choice !== "draft"
      ? session.choice
      : null;

  const activeConversationQuery = useQuery({
    queryKey: knowledgeAgentKeys.conversation(selectedConversationId as number),
    queryFn: () =>
      knowledgeAgentApi.getConversation(token as string, selectedConversationId as number),
    enabled: Boolean(token && selectedConversationId),
  });
  const activeConversation = activeConversationQuery.data ?? null;
  const isDraft = selectedConversationId === null;

  const currentScope = useMemo<KnowledgeScopeChangeRequest>(() => {
    if (isDraft || !activeConversation) return { ...session.scope };
    return {
      scopeType: activeConversation.scopeType,
      projectId: activeConversation.projectId,
      projectName: activeConversation.projectName ?? undefined,
    };
  }, [activeConversation, isDraft, session.scope]);

  const recentPageQuery = useQuery({
    queryKey: knowledgeAgentKeys.messages(selectedConversationId as number),
    queryFn: () =>
      knowledgeAgentApi.listMessages(
        token as string,
        selectedConversationId as number,
        null,
      ),
    enabled: Boolean(token && selectedConversationId),
  });

  const threadBase = useMemo(
    () =>
      composeThread(recentPageQuery.data, olderPages, runOverrides, extraMessages),
    [extraMessages, olderPages, recentPageQuery.data, runOverrides],
  );

  const recoveryRunQuery = useQuery({
    queryKey: knowledgeAgentKeys.run(session.recoveryRun?.runId as number),
    queryFn: () =>
      knowledgeAgentApi.getRun(token as string, session.recoveryRun?.runId as number),
    enabled: Boolean(
      token &&
        appActive &&
        session.bootStatus === "ready" &&
        session.recoveryRun &&
        session.recoveryRun.conversationId === selectedConversationId,
    ),
  });

  const recoveredThreadBase = useMemo(
    () =>
      recoveryRunQuery.data
        ? upsertRun(threadBase, recoveryRunQuery.data)
        : threadBase,
    [recoveryRunQuery.data, threadBase],
  );

  const baseActiveRun = useMemo(() => {
    return [...recoveredThreadBase.runsById.values()]
      .filter((run) => isRunActive(run.status))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;
  }, [recoveredThreadBase.runsById]);
  const activeRunId = baseActiveRun?.id ?? null;

  const runQuery = useQuery({
    queryKey: knowledgeAgentKeys.run(activeRunId as number),
    queryFn: () => knowledgeAgentApi.getRun(token as string, activeRunId as number),
    enabled: Boolean(token && appActive && activeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isRunActive(status) && appActive ? 2000 : false;
    },
  });

  const thread = useMemo(
    () =>
      runQuery.data ? upsertRun(recoveredThreadBase, runQuery.data) : recoveredThreadBase,
    [recoveredThreadBase, runQuery.data],
  );

  const activeRun = useMemo(() => {
    return [...thread.runsById.values()]
      .filter((run) => isRunActive(run.status))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;
  }, [thread.runsById]);

  const resumableRunId = useMemo(() => {
    if (activeRun) return null;
    if (activeConversation?.recentRunId !== null && activeConversation?.recentRunId !== undefined) {
      const recent = thread.runsById.get(activeConversation.recentRunId);
      return recent?.canContinue && !isRunActive(recent.status) ? recent.id : null;
    }
    return [...thread.runsById.values()]
      .filter((run) => run.canContinue && !isRunActive(run.status))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0]?.id ?? null;
  }, [activeConversation, activeRun, thread.runsById]);

  useEffect(() => {
    const status = runQuery.data?.status ?? null;
    if (status === null) return;
    const previous = previousRunStatusRef.current;
    previousRunStatusRef.current = status;
    if (!isRunActive(status) && previous !== status) {
      if (selectedConversationId !== null) {
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
        });
      }
      void queryClient.invalidateQueries({ queryKey: knowledgeAgentKeys.conversations() });
    }
  }, [queryClient, runQuery.data?.status, selectedConversationId]);

  useEffect(() => {
    if (
      !pending ||
      session.pendingState !== "result_unknown" ||
      pending.conversationId === null ||
      pending.conversationId !== selectedConversationId ||
      recentPageQuery.isLoading ||
      !recentPageQuery.data
    ) {
      return;
    }
    const confirmed = recentPageQuery.data.items.find(
      (message) => message.clientMessageId === pending.clientMessageId,
    );
    if (!confirmed) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      session.update({
        input: "",
        pending: null,
        pendingState: null,
        recoveryRun:
          confirmed.runId === null
            ? null
            : { conversationId: pending.conversationId as number, runId: confirmed.runId },
      });
      setSubmitError(null);
    });
    return () => {
      cancelled = true;
    };
  }, [
    pending,
    recentPageQuery.data,
    recentPageQuery.isLoading,
    selectedConversationId,
    session,
  ]);

  useEffect(() => {
    if (!activeConversation || sameScope(session.scope, activeConversation)) return;
    session.update({
      scope: {
        scopeType: activeConversation.scopeType,
        projectId: activeConversation.projectId,
        projectName: activeConversation.projectName ?? undefined,
      },
    });
  }, [activeConversation, session]);

  useEffect(() => {
    if (!activeRun || activeRun.conversationId !== selectedConversationId) return;
    if (
      session.recoveryRun?.conversationId === activeRun.conversationId &&
      session.recoveryRun.runId === activeRun.id
    ) {
      return;
    }
    session.update({
      recoveryRun: {
        conversationId: activeRun.conversationId,
        runId: activeRun.id,
      },
    });
  }, [activeRun, selectedConversationId, session]);

  useEffect(() => {
    if (
      !session.recoveryRun ||
      recentPageQuery.isLoading ||
      recentPageQuery.isError ||
      !recentPageQuery.data
    ) {
      return;
    }
    const recovered = thread.runsById.get(session.recoveryRun.runId);
    if (!recovered || isRunActive(recovered.status)) return;
    session.update({ recoveryRun: null });
  }, [recentPageQuery.data, recentPageQuery.isError, recentPageQuery.isLoading, session, thread.runsById]);

  const resetConversationLocalState = useCallback(() => {
    const nextGeneration = conversationGenerationRef.current + 1;
    conversationGenerationRef.current = nextGeneration;
    setConversationGeneration(nextGeneration);
    olderPageRequestRef.current = null;
    setOlderPages([]);
    setRunOverrides(new Map());
    setExtraMessages([]);
    setOlderError(null);
    setLoadingOlder(false);
    setCancelError(null);
    previousRunStatusRef.current = null;
  }, []);

  const switchToConversation = useCallback(
    (conversationId: number) => {
      if (pending) {
        setSubmitError("当前消息结果尚未确认，请先重试或等待返回");
        return;
      }
      resetConversationLocalState();
      session.update({
        choice: conversationId,
        input: "",
        recoveryRun: null,
      });
    },
    [pending, resetConversationLocalState, session],
  );

  const startNewConversation = useCallback(() => {
    if (pending) {
      setSubmitError("当前消息结果尚未确认，请先重试或等待返回");
      return;
    }
    resetConversationLocalState();
    session.update({
      choice: "draft",
      input: "",
      pending: null,
      pendingState: null,
      recoveryRun: null,
    });
    setModesState(DEFAULT_MODES);
  }, [pending, resetConversationLocalState, session]);

  const loadOlderMessages = useCallback(async () => {
    if (
      !token ||
      selectedConversationId === null ||
      olderPageRequestRef.current !== null ||
      !thread.nextCursor
    ) {
      return;
    }
    const request: OlderPageRequest = {
      conversationId: selectedConversationId,
      generation: conversationGenerationRef.current,
      cursor: thread.nextCursor,
    };
    olderPageRequestRef.current = request;
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const page = await knowledgeAgentApi.listMessages(
        token,
        request.conversationId,
        request.cursor,
      );
      if (
        olderPageRequestRef.current !== request ||
        conversationGenerationRef.current !== request.generation
      ) {
        return;
      }
      setOlderPages((previous) => [...previous, page]);
    } catch (error) {
      if (
        olderPageRequestRef.current !== request ||
        conversationGenerationRef.current !== request.generation
      ) {
        return;
      }
      setOlderError(toUserErrorMessage(error));
    } finally {
      if (
        olderPageRequestRef.current === request &&
        conversationGenerationRef.current === request.generation
      ) {
        olderPageRequestRef.current = null;
        setLoadingOlder(false);
      }
    }
  }, [selectedConversationId, thread.nextCursor, token]);

  const performSubmission = useCallback(
    async (initial: PendingSubmission): Promise<boolean> => {
      if (!token || submissionRequestRef.current) return false;
      submissionRequestRef.current = true;
      setSubmitting(true);
      session.update({ pending: initial, pendingState: "in_flight" });
      setSubmitError(null);
      setCancelError(null);
      let current = initial;
      try {
        const targetConversationId = current.conversationId ?? selectedConversationId;
        if (targetConversationId === null) {
          const created = await knowledgeAgentApi.createConversation(token, session.scope);
          current = attachConversation(current, created.id);
          session.update({
            choice: created.id,
            pending: current,
            pendingState: "in_flight",
          });
        } else if (current.conversationId === null) {
          current = attachConversation(current, targetConversationId);
          session.update({ pending: current, pendingState: "in_flight" });
        }
        const conversationId = current.conversationId as number;
        const result = await knowledgeAgentApi.submitMessage(token, conversationId, {
          clientMessageId: current.clientMessageId,
          message: current.text,
          contextMode: current.contextMode,
        });
        session.update({
          choice: conversationId,
          input: "",
          pending: null,
          pendingState: null,
          recoveryRun: { conversationId, runId: result.run.id },
        });
        setModesState(DEFAULT_MODES);
        setExtraMessages((previous) => [...previous, result.userMessage]);
        setRunOverrides((previous) => new Map(previous).set(result.run.id, result.run));
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(conversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(conversationId),
        });
        void queryClient.invalidateQueries({ queryKey: knowledgeAgentKeys.conversations() });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        if (classified.kind === "conflict") {
          session.update({ pending: null, pendingState: null });
          setSubmitError("已有进行中的回答，请等待完成或取消后再提问");
          const conversationId = current.conversationId ?? selectedConversationId;
          if (conversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(conversationId),
            });
          }
          return false;
        }
        if (classified.kind === "network") {
          session.update({
            pending: current,
            pendingState:
              current.conversationId === null
                ? "creation_unknown"
                : "result_unknown",
          });
        } else {
          session.update({ pending: null, pendingState: null });
        }
        setSubmitError(classified.message);
        return false;
      } finally {
        submissionRequestRef.current = false;
        setSubmitting(false);
      }
    },
    [queryClient, selectedConversationId, session, token],
  );

  const submitWithContext = useCallback(
    async (text: string, contextMode: ContextMode): Promise<boolean> => {
      const trimmed = text.trim();
      if (!trimmed || pending || submissionRequestRef.current || !token || activeRun) {
        return false;
      }
      const created = createPendingSubmission({ text: trimmed, contextMode });
      const submission =
        selectedConversationId === null
          ? created
          : attachConversation(created, selectedConversationId);
      session.update({ pending: submission, pendingState: "in_flight" });
      return performSubmission(submission);
    },
    [activeRun, pending, performSubmission, selectedConversationId, session, token],
  );

  const submit = useCallback(
    (text: string) => submitWithContext(text, modesRef.current.contextMode),
    [submitWithContext],
  );

  const continueRun = useCallback(
    async (runId: number): Promise<boolean> => {
      if (selectedConversationId === null || activeRun || pending) return false;
      const run = thread.runsById.get(runId);
      if (
        !run ||
        run.conversationId !== selectedConversationId ||
        run.id !== resumableRunId ||
        !run.canContinue ||
        isRunActive(run.status)
      ) {
        setSubmitError("这轮任务当前不能继续，请刷新会话后再试");
        return false;
      }
      return submitWithContext("继续", "auto");
    },
    [
      activeRun,
      pending,
      resumableRunId,
      selectedConversationId,
      submitWithContext,
      thread.runsById,
    ],
  );

  const retrySubmit = useCallback(() => {
    if (
      !pending ||
      !submissionResultUnknown ||
      pending.conversationId === null ||
      submissionRequestRef.current ||
      !canRetrySubmission(pending)
    ) {
      return Promise.resolve(false);
    }
    return performSubmission(pending);
  }, [pending, performSubmission, submissionResultUnknown]);

  const retryRun = useCallback(
    async (runId: number): Promise<boolean> => {
      if (pending || activeRun || !token) return false;
      const run = thread.runsById.get(runId);
      const userMessage = thread.items.find(
        (message) =>
          message.role === "user" &&
          (message.id === run?.userMessageId || message.runId === runId),
      );
      if (!run || !userMessage) {
        setSubmitError("原问题尚未加载，向上加载历史后再试");
        return false;
      }
      return submitWithContext(
        userMessage.content,
        run.requestContextMode ?? userMessage.requestContextMode ?? "auto",
      );
    },
    [activeRun, pending, submitWithContext, thread.items, thread.runsById, token],
  );

  const scopeMutation = useMutation({
    mutationFn: ({ conversationId, scope }: ConversationRequestOwner & {
      scope: KnowledgeScopeChangeRequest;
    }) =>
      knowledgeAgentApi.changeScope(
        token as string,
        conversationId,
        scope,
      ),
    onSuccess: (conversation, request) => {
      queryClient.setQueryData(
        knowledgeAgentKeys.conversation(conversation.id),
        conversation,
      );
      void queryClient.invalidateQueries({
        queryKey: knowledgeAgentKeys.messages(conversation.id),
      });
      void queryClient.invalidateQueries({ queryKey: knowledgeAgentKeys.conversations() });
      if (conversationGenerationRef.current !== request.generation) return;
      setScopeError(null);
      session.update({
        scope: {
          scopeType: conversation.scopeType,
          projectId: conversation.projectId,
          projectName: conversation.projectName ?? undefined,
        },
      });
      resetConversationLocalState();
    },
    onError: (error, request) => {
      if (conversationGenerationRef.current === request.generation) {
        setScopeError(toUserErrorMessage(error));
      }
    },
  });

  const changeScope = useCallback(
    async (scope: KnowledgeScopeChangeRequest) => {
      setScopeError(null);
      if (activeRun) {
        setScopeError("正在回答中，完成或取消后再切换范围");
        return;
      }
      if (isDraft) {
        session.update({ scope });
        return;
      }
      if (sameScope(currentScope, scope)) return;
      if (selectedConversationId === null) return;
      await scopeMutation
        .mutateAsync({
          conversationId: selectedConversationId,
          generation: conversationGenerationRef.current,
          scope,
        })
        .catch(() => undefined);
    },
    [activeRun, currentScope, isDraft, scopeMutation, selectedConversationId, session],
  );

  const cancelMutation = useMutation({
    mutationFn: ({ runId }: ConversationRequestOwner & { runId: number }) =>
      knowledgeAgentApi.cancelRun(token as string, runId),
    onSuccess: (run, request) => {
      void queryClient.invalidateQueries({ queryKey: knowledgeAgentKeys.run(run.id) });
      if (conversationGenerationRef.current !== request.generation) return;
      setCancelError(null);
      setRunOverrides((previous) => new Map(previous).set(run.id, run));
    },
    onError: (error, request) => {
      if (conversationGenerationRef.current === request.generation) {
        setCancelError({ runId: request.runId, message: toUserErrorMessage(error) });
      }
    },
  });

  const requestCancelRun = useCallback(async () => {
    if (!activeRun) return;
    await cancelMutation
      .mutateAsync({
        conversationId: activeRun.conversationId,
        generation: conversationGenerationRef.current,
        runId: activeRun.id,
      })
      .catch(() => undefined);
  }, [activeRun, cancelMutation]);

  const hasRemoteRecovery = Boolean(
    session.choice !== "draft" &&
      (session.pending || session.recoveryRun || session.input.trim()),
  );
  const recoveryError =
    session.bootStatus === "error"
      ? session.bootError ?? "移动对话恢复记录读取失败"
      : hasRemoteRecovery && activeConversationQuery.isError
        ? toUserErrorMessage(activeConversationQuery.error)
        : hasRemoteRecovery && recentPageQuery.isError
          ? toUserErrorMessage(recentPageQuery.error)
          : session.recoveryRun && recoveryRunQuery.isError
            ? toUserErrorMessage(recoveryRunQuery.error)
            : null;

  const retryRecovery = useCallback(() => {
    if (session.bootStatus === "error") {
      session.retryBootstrap();
      return;
    }
    if (selectedConversationId !== null) {
      void activeConversationQuery.refetch();
      void recentPageQuery.refetch();
    }
    if (session.recoveryRun) void recoveryRunQuery.refetch();
  }, [
    activeConversationQuery,
    recentPageQuery,
    recoveryRunQuery,
    selectedConversationId,
    session,
  ]);

  const exitRecovery = useCallback(async () => {
    resetConversationLocalState();
    setSubmitError(null);
    await session.exitRecovery();
  }, [resetConversationLocalState, session]);

  return {
    initialLoading:
      session.bootStatus === "loading" ||
      (hasRemoteRecovery &&
        (activeConversationQuery.isLoading ||
          recentPageQuery.isLoading ||
          Boolean(session.recoveryRun && recoveryRunQuery.isLoading))),
    conversations,
    conversationsLoading: conversationsQuery.isLoading,
    conversationsError: conversationsQuery.isError
      ? toUserErrorMessage(conversationsQuery.error)
      : null,
    activeConversation,
    activeConversationLoading: activeConversationQuery.isLoading,
    isDraft,
    userInitiatedDraft: session.choice === "draft",
    currentScope,
    scopeLabel: scopeLabelOf(currentScope),
    scopeBusy:
      scopeMutation.isPending &&
      scopeMutation.variables?.generation === conversationGeneration,
    scopeError,
    changeScope,
    switchToConversation,
    startNewConversation,
    retryConversations: () => void conversationsQuery.refetch(),
    thread,
    messagesLoading: recentPageQuery.isLoading,
    messagesError: recentPageQuery.isError
      ? toUserErrorMessage(recentPageQuery.error)
      : null,
    loadOlderMessages,
    loadingOlder,
    olderError,
    pending,
    input: session.input,
    setInput: (value) => session.update({ input: value }),
    submitting,
    submissionResultUnknown,
    conversationCreationUnknown,
    submitError,
    recoveryError,
    persistenceError: session.persistenceError,
    retryRecovery,
    retryPersistence: session.retryPersistence,
    exitRecovery,
    getReadingPosition: session.getReadingPosition,
    setReadingPosition: session.setReadingPosition,
    clearReadingPosition: session.clearReadingPosition,
    modes,
    setContextMode: (mode) => setModesState((previous) => withContextMode(previous, mode)),
    setModes: setModesState,
    submit,
    continueRun,
    retrySubmit,
    retryRun,
    resumableRunId,
    activeRun,
    runPolling: Boolean(activeRun && runQuery.isFetching),
    runPollingError: runQuery.isError ? toUserErrorMessage(runQuery.error) : null,
    retryRunPolling: () => void runQuery.refetch(),
    cancelling:
      cancelMutation.isPending &&
      cancelMutation.variables?.generation === conversationGeneration &&
      cancelMutation.variables.runId === activeRun?.id,
    cancelError:
      activeRun && cancelError?.runId === activeRun.id ? cancelError.message : null,
    requestCancelRun,
    appActive,
  };
}
