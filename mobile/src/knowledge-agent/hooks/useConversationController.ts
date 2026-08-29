import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import {
  classifyKnowledgeAgentError,
  toUserErrorMessage,
} from "@/src/knowledge-agent/errors";
import { useAppStateActive } from "@/src/knowledge-agent/hooks/useAppState";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";
import {
  composeThread,
  upsertRun,
  type MessageThreadState,
} from "@/src/knowledge-agent/state/messages";
import {
  DEFAULT_MODES,
  withAnswerMode,
  withContextMode,
  type ModeSelection,
} from "@/src/knowledge-agent/state/modes";
import {
  attachConversation,
  canRetrySubmission,
  createPendingSubmission,
  markConflict,
  type PendingSubmission,
} from "@/src/knowledge-agent/state/submission";
import type {
  AnswerMode,
  ContextMode,
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
  RunStatus,
  KnowledgeScopeChangeRequest,
  KnowledgeScopeType,
} from "@/src/knowledge-agent/types";
import { isRunActive } from "@/src/knowledge-agent/types";

export interface DraftScope {
  scopeType: KnowledgeScopeType;
  projectId: number | null;
}

export interface ConversationController {
  initialLoading: boolean;
  conversations: KnowledgeConversation[] | undefined;
  conversationsError: string | null;
  activeConversation: KnowledgeConversation | null;
  activeConversationLoading: boolean;
  isDraft: boolean;
  draftScope: DraftScope;
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
  submitError: string | null;
  modes: ModeSelection;
  setContextMode: (mode: ContextMode) => void;
  setAnswerMode: (mode: AnswerMode) => void;
  setModes: (modes: ModeSelection) => void;
  submit: (text: string) => Promise<boolean>;
  retrySubmit: () => Promise<boolean>;
  retryRun: (runId: number) => Promise<boolean>;
  activeRun: KnowledgeRun | null;
  runPolling: boolean;
  runPollingError: string | null;
  retryRunPolling: () => void;
  cancelling: boolean;
  requestCancelRun: () => void;
  appActive: boolean;
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

function scopeLabelOf(scope: KnowledgeScopeChangeRequest): string {
  if (scope.scopeType === "project") {
    return scope.projectName ?? "项目";
  }
  return "全部知识";
}

export function useConversationController(
  token: string | null,
): ConversationController {
  const queryClient = useQueryClient();
  const appActive = useAppStateActive();
  // null = 尚未选择；"draft" = 用户明确新建；数字 = 用户/自动选择的对话
  const [explicitChoice, setExplicitChoice] = useState<
    number | "draft" | null
  >(null);
  const [draftScope, setDraftScope] = useState<DraftScope>({
    scopeType: "workspace",
    projectId: null,
  });
  const [olderPages, setOlderPages] = useState<KnowledgeMessagePage[]>([]);
  const [runOverrides, setRunOverrides] = useState<Map<number, KnowledgeRun>>(
    () => new Map(),
  );
  const [extraMessages, setExtraMessages] = useState<KnowledgeMessage[]>([]);
  const [pending, setPending] = useState<PendingSubmission | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [modes, setModesState] = useState<ModeSelection>(DEFAULT_MODES);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const previousRunStatusRef = useRef<RunStatus | null>(null);
  const modesRef = useRef<ModeSelection>(DEFAULT_MODES);
  useEffect(() => {
    modesRef.current = modes;
  }, [modes]);

  const conversationsQuery = useQuery({
    queryKey: knowledgeAgentKeys.conversations(),
    queryFn: () => knowledgeAgentApi.listConversations(token as string),
    enabled: Boolean(token),
  });
  const conversations = conversationsQuery.data;

  // 启动恢复：有历史时默认打开最近活动对话；没有或用户点「新对话」进入 draft。
  // 选择是派生状态，避免在 effect 中同步 setState。
  const selectedConversationId =
    explicitChoice === null
      ? conversations && conversations.length > 0
        ? conversations[0].id
        : null
      : explicitChoice === "draft"
        ? null
        : explicitChoice;

  const activeConversationQuery = useQuery({
    queryKey: knowledgeAgentKeys.conversation(
      selectedConversationId as number,
    ),
    queryFn: () =>
      knowledgeAgentApi.getConversation(
        token as string,
        selectedConversationId as number,
      ),
    enabled: Boolean(token && selectedConversationId),
  });
  const activeConversation = activeConversationQuery.data ?? null;
  const isDraft = selectedConversationId === null;

  const currentScope: KnowledgeScopeChangeRequest = useMemo(() => {
    if (isDraft || !activeConversation) {
      return {
        scopeType: draftScope.scopeType,
        projectId: draftScope.projectId,
      };
    }
    return {
      scopeType: activeConversation.scopeType,
      projectId: activeConversation.projectId,
      projectName: activeConversation.projectName ?? undefined,
    };
  }, [isDraft, activeConversation, draftScope]);

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
      composeThread(
        recentPageQuery.data,
        olderPages,
        runOverrides,
        extraMessages,
      ),
    [recentPageQuery.data, olderPages, runOverrides, extraMessages],
  );

  const activeRun = useMemo(() => {
    const runs = [...threadBase.runsById.values()].filter((run) =>
      isRunActive(run.status),
    );
    if (runs.length === 0) return null;
    return runs.sort((left, right) =>
      right.updatedAt.localeCompare(left.updatedAt),
    )[0];
  }, [threadBase.runsById]);

  const activeRunId = activeRun?.id ?? null;

  // 仅在前台且 Run 未终态时轮询；进入后台停止，回到前台立即恢复
  const runQuery = useQuery({
    queryKey: knowledgeAgentKeys.run(activeRunId as number),
    queryFn: () => knowledgeAgentApi.getRun(token as string, activeRunId as number),
    enabled: Boolean(token && appActive && activeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isRunActive(status) && appActive ? 2000 : false;
    },
  });

  // 轮询结果直接参与线程组合（服务端权威），不再复制进本地状态
  const thread = useMemo(() => {
    if (!runQuery.data) return threadBase;
    return upsertRun(threadBase, runQuery.data);
  }, [threadBase, runQuery.data]);

  // Run 进入终态后同步服务端消息与对话摘要（助手回答内容、最近 Run 状态）
  useEffect(() => {
    const status: RunStatus | null = runQuery.data?.status ?? null;
    if (status === null) return;
    const previous = previousRunStatusRef.current;
    previousRunStatusRef.current = status;
    if (previous !== null && isRunActive(previous) && !isRunActive(status)) {
      if (selectedConversationId !== null) {
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(selectedConversationId),
        });
      }
      void queryClient.invalidateQueries({
        queryKey: knowledgeAgentKeys.conversations(),
      });
      if (selectedConversationId !== null) {
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
        });
      }
    }
  }, [runQuery.data?.status, selectedConversationId, queryClient]);

  const loadOlderMessages = useCallback(async () => {
    if (
      !token ||
      selectedConversationId === null ||
      loadingOlder ||
      !thread.nextCursor
    ) {
      return;
    }
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const page = await knowledgeAgentApi.listMessages(
        token,
        selectedConversationId,
        thread.nextCursor,
      );
      setOlderPages((previous) => [...previous, page]);
    } catch (error) {
      setOlderError(toUserErrorMessage(error));
    } finally {
      setLoadingOlder(false);
    }
  }, [token, selectedConversationId, loadingOlder, thread.nextCursor]);

  const performSubmission = useCallback(
    async (submission: PendingSubmission): Promise<boolean> => {
      if (!token) return false;
      setSubmitError(null);
      let current = submission;
      try {
        // 目标对话：优先复用提交中已固化的 conversation_id（网络重试路径），
        // 否则使用当前选中的对话；只有本地草稿（没有对话）才首次发送时创建。
        const targetConversationId =
          current.conversationId ?? selectedConversationId;
        if (targetConversationId === null) {
          const created = await knowledgeAgentApi.createConversation(token, {
            scopeType: draftScope.scopeType,
            projectId: draftScope.projectId,
          });
          setExplicitChoice(created.id);
          current = attachConversation(current, created.id);
          setPending(current);
        } else if (current.conversationId === null) {
          current = attachConversation(current, targetConversationId);
          setPending(current);
        }
        const conversationId = current.conversationId as number;
        const result = await knowledgeAgentApi.submitMessage(token, conversationId, {
          clientMessageId: current.clientMessageId,
          message: current.text,
          contextMode: current.contextMode,
          answerMode: current.answerMode,
        });
        setPending(null);
        setModesState(DEFAULT_MODES);
        setExtraMessages((previous) => [...previous, result.userMessage]);
        setRunOverrides((previous) => {
          const next = new Map(previous);
          next.set(result.run.id, result.run);
          return next;
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(conversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(conversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversations(),
        });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        if (classified.kind === "conflict") {
          // 活动 Run 409：不创建第二个本地任务，刷新并展示服务端最近 Run
          setPending(markConflict(submission));
          const conversationId =
            submission.conversationId ?? selectedConversationId;
          if (conversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversation(conversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(conversationId),
            });
          }
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversations(),
          });
          return false;
        } else if (
          classified.kind === "network" ||
          classified.kind === "server" ||
          classified.kind === "cancelled"
        ) {
          // 结果未知：保留对话 id、文本与同一幂等键，等待用户重试
          setPending(current);
          setSubmitError(classified.message);
          return false;
        } else {
          setPending(null);
          setSubmitError(classified.message);
          return false;
        }
      }
    },
    [token, draftScope, queryClient, selectedConversationId],
  );

  const submit = useCallback(
    async (rawText: string): Promise<boolean> => {
      const text = rawText.trim();
      if (!text || pending || !token) return false;
      const submission = createPendingSubmission({
        text,
        contextMode: modesRef.current.contextMode,
        answerMode: modesRef.current.answerMode,
      });
      setPending(submission);
      return performSubmission(submission);
    },
    [pending, token, performSubmission],
  );

  const retrySubmit = useCallback(async () => {
    if (!pending || !canRetrySubmission(pending)) return false;
    return performSubmission(pending);
  }, [pending, performSubmission]);

  const retryRun = useCallback(
    async (runId: number): Promise<boolean> => {
      if (pending || !token) return false;
      const userMessage = thread.items.find(
        (message) => message.runId === runId && message.role === "user",
      );
      if (!userMessage) return false;
      const submission = createPendingSubmission({
        text: userMessage.content,
        contextMode: modesRef.current.contextMode,
        answerMode: modesRef.current.answerMode,
      });
      setPending(submission);
      return performSubmission(submission);
    },
    [pending, token, thread.items, performSubmission],
  );

  const scopeMutation = useMutation({
    mutationFn: ({
      conversationId,
      scope,
    }: {
      conversationId: number;
      scope: KnowledgeScopeChangeRequest;
    }) => knowledgeAgentApi.changeScope(token as string, conversationId, scope),
  });

  const changeScope = useCallback(
    async (scope: KnowledgeScopeChangeRequest) => {
      if (!token) return;
      if (isDraft) {
        setDraftScope({
          scopeType: scope.scopeType,
          projectId: scope.projectId ?? null,
        });
        setScopeError(null);
        return;
      }
      if (selectedConversationId === null) return;
      if (sameScope(scope, currentScope)) return;
      if (activeRun) return; // UI 已禁用；服务端 409 作为最终防线
      setScopeError(null);
      try {
        await scopeMutation.mutateAsync({
          conversationId: selectedConversationId,
          scope,
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversations(),
        });
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        if (classified.kind === "conflict" && selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
        }
        setScopeError(classified.message);
      }
    },
    [
      token,
      isDraft,
      selectedConversationId,
      currentScope,
      activeRun,
      scopeMutation,
      queryClient,
    ],
  );

  const switchToConversation = useCallback((conversationId: number) => {
    setOlderPages([]);
    setRunOverrides(new Map());
    setExtraMessages([]);
    setPending(null);
    setSubmitError(null);
    setModesState(DEFAULT_MODES);
    setScopeError(null);
    setExplicitChoice(conversationId);
  }, []);

  const startNewConversation = useCallback(() => {
    setOlderPages([]);
    setRunOverrides(new Map());
    setExtraMessages([]);
    setPending(null);
    setSubmitError(null);
    setModesState(DEFAULT_MODES);
    setScopeError(null);
    setExplicitChoice("draft");
  }, []);

  const cancelMutation = useMutation({
    mutationFn: (runId: number) =>
      knowledgeAgentApi.cancelRun(token as string, runId),
  });

  const requestCancelRun = useCallback(() => {
    if (!activeRunId) return;
    void cancelMutation
      .mutateAsync(activeRunId)
      .then(() => {
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.run(activeRunId),
        });
      })
      .catch(() => {
        // 取消请求失败：保持轮询，展示服务端真实状态
      });
  }, [activeRunId, cancelMutation, queryClient]);

  const setContextMode = useCallback((mode: ContextMode) => {
    setModesState((previous) => withContextMode(previous, mode));
  }, []);
  const setAnswerMode = useCallback((mode: AnswerMode) => {
    setModesState((previous) => withAnswerMode(previous, mode));
  }, []);
  const setModes = (next: ModeSelection) => {
    setModesState({ ...next });
  };

  return {
    initialLoading: conversationsQuery.isLoading,
    conversations,
    conversationsError: conversationsQuery.isError
      ? toUserErrorMessage(conversationsQuery.error)
      : null,
    activeConversation,
    activeConversationLoading: activeConversationQuery.isLoading,
    isDraft,
    draftScope,
    currentScope,
    scopeLabel: scopeLabelOf(currentScope),
    scopeBusy: scopeMutation.isPending,
    scopeError,
    changeScope,
    switchToConversation,
    startNewConversation,
    retryConversations: () => {
      void conversationsQuery.refetch();
    },
    thread,
    messagesLoading: recentPageQuery.isLoading,
    messagesError: recentPageQuery.isError
      ? toUserErrorMessage(recentPageQuery.error)
      : null,
    loadOlderMessages,
    loadingOlder,
    olderError,
    pending,
    submitError,
    modes,
    setContextMode,
    setAnswerMode,
    setModes,
    submit,
    retrySubmit,
    retryRun,
    activeRun,
    runPolling: Boolean(runQuery.data && isRunActive(runQuery.data.status)),
    runPollingError: runQuery.isError
      ? toUserErrorMessage(runQuery.error)
      : null,
    retryRunPolling: () => {
      void runQuery.refetch();
    },
    cancelling: cancelMutation.isPending || Boolean(activeRun?.cancelRequested),
    requestCancelRun,
    appActive,
  };
}
