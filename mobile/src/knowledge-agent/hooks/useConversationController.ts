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
  withResultMode,
  type ModeSelection,
} from "@/src/knowledge-agent/state/modes";
import {
  attachConversation,
  canRetrySubmission,
  createPendingSubmission,
  nextClientMessageId,
  nextClientOperationId,
  type PendingSubmission,
} from "@/src/knowledge-agent/state/submission";
import type {
  AnswerMode,
  ContextMode,
  KnowledgeCandidateDraft,
  KnowledgeConversation,
  KnowledgeDraftEditRequest,
  KnowledgeEntryResultItem,
  KnowledgeEntryRevisionDraft,
  KnowledgeMessage,
  KnowledgeMessagePage,
  KnowledgeRun,
  RunStatus,
  ResultMode,
  KnowledgeScopeChangeRequest,
  KnowledgeScopeType,
  KnowledgeRevisionEditRequest,
} from "@/src/knowledge-agent/types";
import { isRunActive } from "@/src/knowledge-agent/types";
import { ENTRY_RESULT_PAGE_SIZE } from "@/src/knowledge-agent/adapters/entryResults";

export interface EntryResultsState {
  runId: number;
  items: KnowledgeEntryResultItem[];
  nextCursor: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  error: string | null;
  primed: boolean;
}

function emptyEntryResultsState(runId: number): EntryResultsState {
  return {
    runId,
    items: [],
    nextCursor: null,
    hasMore: false,
    loadingMore: false,
    error: null,
    primed: false,
  };
}

function mergeEntryItems(
  previous: KnowledgeEntryResultItem[],
  incoming: KnowledgeEntryResultItem[],
): KnowledgeEntryResultItem[] {
  const seen = new Set(previous.map((item) => item.entryId));
  const result = [...previous];
  for (const item of incoming) {
    if (seen.has(item.entryId)) continue;
    seen.add(item.entryId);
    result.push(item);
  }
  return result;
}

export interface DraftScope {
  scopeType: KnowledgeScopeType;
  projectId: number | null;
  projectName?: string;
}

export interface ConversationController {
  initialLoading: boolean;
  conversations: KnowledgeConversation[] | undefined;
  conversationsError: string | null;
  activeConversation: KnowledgeConversation | null;
  activeConversationLoading: boolean;
  isDraft: boolean;
  userInitiatedDraft: boolean;
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
  setResultMode: (mode: ResultMode) => void;
  setModes: (modes: ModeSelection) => void;
  /** 结构化 Entry 结果分页：按 Run 归并、去重追加；失败保留已加载项。 */
  entryResultsForRun: (runId: number) => EntryResultsState | null;
  primeEntryResults: (runId: number) => void;
  loadMoreEntryResults: (runId: number) => void;
  retryEntryResults: (runId: number) => void;
  submit: (text: string) => Promise<boolean>;
  retrySubmit: () => Promise<boolean>;
  retryRun: (runId: number) => Promise<boolean>;
  /** 候选草稿：按 id 与 operation Run id 检索，状态以服务端为权威 */
  draftsById: Map<number, KnowledgeCandidateDraft>;
  draftByRunId: (runId: number) => KnowledgeCandidateDraft | null;
  submitDraftAction: (
    sourceRunId: number,
    targetProjectId?: number | null,
  ) => Promise<boolean>;
  draftActionPending: boolean;
  draftActionError: string | null;
  retryDraftAction: () => Promise<boolean>;
  editDraft: (
    draftId: number,
    fields: KnowledgeDraftEditRequest,
  ) => Promise<boolean>;
  clearDraftEditError: () => void;
  draftEditBusy: boolean;
  draftEditError: string | null;
  confirmDraft: (draftId: number) => Promise<boolean>;
  retryConfirmDraft: (draftId: number) => Promise<boolean>;
  confirmingDraftId: number | null;
  draftConfirmError: string | null;
  cancelDraft: (draftId: number) => Promise<boolean>;
  draftCancelBusy: boolean;
  draftCancelError: string | null;
  clearDraftCancelError: () => void;
  /** 单 Entry 修订：按 id 与 operation Run id 检索，状态以服务端为权威 */
  revisionDraftsById: Map<number, KnowledgeEntryRevisionDraft>;
  revisionDraftByRunId: (runId: number) => KnowledgeEntryRevisionDraft | null;
  submitEntryRevision: (
    sourceRunId: number,
    targetEntryId: number,
    instruction: string,
  ) => Promise<boolean>;
  revisionActionPending: boolean;
  revisionActionError: string | null;
  retryEntryRevision: () => Promise<boolean>;
  editEntryRevision: (
    draftId: number,
    fields: KnowledgeRevisionEditRequest,
  ) => Promise<boolean>;
  clearRevisionEditError: () => void;
  revisionEditBusy: boolean;
  revisionEditError: string | null;
  confirmEntryRevision: (draftId: number) => Promise<boolean>;
  retryConfirmEntryRevision: (draftId: number) => Promise<boolean>;
  confirmingRevisionDraftId: number | null;
  revisionConfirmError: string | null;
  /** 网络结果未知时保留幂等键，可重试；确定性 409/404 后不可重试。 */
  revisionConfirmRetryable: boolean;
  undoEntryRevision: (draftId: number) => Promise<boolean>;
  retryUndoEntryRevision: (draftId: number) => Promise<boolean>;
  undoingRevisionDraftId: number | null;
  revisionUndoError: string | null;
  revisionUndoRetryable: boolean;
  /** 撤销错误归属的草稿 id（用于回执持久展示冲突说明）。 */
  revisionUndoErrorDraftId: number | null;
  cancelEntryRevision: (draftId: number) => Promise<boolean>;
  revisionCancelBusy: boolean;
  revisionCancelError: string | null;
  clearRevisionCancelError: () => void;
  activeRun: KnowledgeRun | null;
  runPolling: boolean;
  runPollingError: string | null;
  retryRunPolling: () => void;
  cancelling: boolean;
  cancelError: string | null;
  requestCancelRun: () => void;
  appActive: boolean;
}

interface RunCancelError {
  runId: number;
  message: string;
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
  const [entryResultsByRun, setEntryResultsByRun] = useState<
    Map<number, EntryResultsState>
  >(() => new Map());
  const [extraMessages, setExtraMessages] = useState<KnowledgeMessage[]>([]);
  const [threadDrafts, setThreadDrafts] = useState<
    Map<number, KnowledgeCandidateDraft>
  >(() => new Map());
  const [threadRevisionDrafts, setThreadRevisionDrafts] = useState<
    Map<number, KnowledgeEntryRevisionDraft>
  >(() => new Map());
  const [pending, setPending] = useState<PendingSubmission | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [modes, setModesState] = useState<ModeSelection>(DEFAULT_MODES);
  const [scopeError, setScopeError] = useState<string | null>(null);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [cancelError, setCancelError] = useState<RunCancelError | null>(null);
  // ---- 候选草稿操作状态 ----
  const [draftActionPending, setDraftActionPending] = useState(false);
  const [draftActionError, setDraftActionError] = useState<string | null>(null);
  const draftActionRef = useRef<{
    clientMessageId: string;
    sourceRunId: number;
    targetProjectId: number | null;
  } | null>(null);
  // 稳定确认幂等键：网络结果未知时重试复用原键，服务端 Draft/Candidate 为权威
  const pendingConfirmsRef = useRef<Map<number, string>>(new Map());
  const [confirmingDraftId, setConfirmingDraftId] = useState<number | null>(
    null,
  );
  const [draftConfirmError, setDraftConfirmError] = useState<string | null>(
    null,
  );
  const [draftEditBusy, setDraftEditBusy] = useState(false);
  const [draftEditError, setDraftEditError] = useState<string | null>(null);
  const [draftCancelBusy, setDraftCancelBusy] = useState(false);
  const [draftCancelError, setDraftCancelError] = useState<string | null>(null);
  // ---- 单 Entry 修订操作状态 ----
  const [revisionActionPending, setRevisionActionPending] = useState(false);
  const [revisionActionError, setRevisionActionError] = useState<string | null>(
    null,
  );
  const revisionActionRef = useRef<{
    clientMessageId: string;
    sourceRunId: number;
    targetEntryId: number;
    instruction: string;
  } | null>(null);
  // 稳定确认/撤销幂等键：网络结果未知时重试复用原键，服务端 Draft/Execution 为权威
  const pendingRevisionConfirmsRef = useRef<Map<number, string>>(new Map());
  const pendingRevisionUndoRef = useRef<Map<number, string>>(new Map());
  const [confirmingRevisionDraftId, setConfirmingRevisionDraftId] = useState<
    number | null
  >(null);
  const [revisionConfirmError, setRevisionConfirmError] = useState<string | null>(
    null,
  );
  const [revisionConfirmRetryable, setRevisionConfirmRetryable] = useState(false);
  const [undoingRevisionDraftId, setUndoingRevisionDraftId] = useState<
    number | null
  >(null);
  const [revisionUndoError, setRevisionUndoError] = useState<string | null>(null);
  const [revisionUndoRetryable, setRevisionUndoRetryable] = useState(false);
  const [revisionUndoErrorDraftId, setRevisionUndoErrorDraftId] = useState<
    number | null
  >(null);
  const [revisionEditBusy, setRevisionEditBusy] = useState(false);
  const [revisionEditError, setRevisionEditError] = useState<string | null>(null);
  const [revisionCancelBusy, setRevisionCancelBusy] = useState(false);
  const [revisionCancelError, setRevisionCancelError] = useState<string | null>(
    null,
  );
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
        projectName: draftScope.projectName,
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
        threadDrafts,
        threadRevisionDrafts,
      ),
    [
      recentPageQuery.data,
      olderPages,
      runOverrides,
      extraMessages,
      threadDrafts,
      threadRevisionDrafts,
    ],
  );

  const baseActiveRun = useMemo(() => {
    const runs = [...threadBase.runsById.values()].filter((run) =>
      isRunActive(run.status),
    );
    if (runs.length === 0) return null;
    return runs.sort((left, right) =>
      right.updatedAt.localeCompare(left.updatedAt),
    )[0];
  }, [threadBase.runsById]);

  const activeRunId = baseActiveRun?.id ?? null;

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

  // 轮询直接返回终态时，用该服务端结果覆盖旧消息页中的 processing Run。
  const activeRun = useMemo(() => {
    const runs = new Map(threadBase.runsById);
    if (runQuery.data) runs.set(runQuery.data.id, runQuery.data);
    const active = [...runs.values()].filter((run) => isRunActive(run.status));
    if (active.length === 0) return null;
    return active.sort((left, right) =>
      right.updatedAt.localeCompare(left.updatedAt),
    )[0];
  }, [threadBase.runsById, runQuery.data]);

  // Run 进入终态后同步服务端消息与对话摘要（助手回答内容、最近 Run 状态）
  useEffect(() => {
    const status: RunStatus | null = runQuery.data?.status ?? null;
    if (status === null) return;
    const previous = previousRunStatusRef.current;
    previousRunStatusRef.current = status;
    if (!isRunActive(status) && previous !== status) {
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
      setCancelError(null);
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
          resultMode: current.resultMode,
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
          // 活动 Run 409：服务端未接受该消息，清空 pending 不显示“发送中”，
          // 刷新并展示服务端最近 Run；错误文案说明冲突原因，不提供重试。
          setPending(null);
          setSubmitError("已有进行中的回答，请等待完成或取消后再提问");
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
        resultMode: modesRef.current.resultMode,
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
        resultMode: modesRef.current.resultMode,
      });
      setPending(submission);
      return performSubmission(submission);
    },
    [pending, token, thread.items, performSubmission],
  );

  const performDraftAction = useCallback(
    async (
      sourceRunId: number,
      targetProjectId: number | null,
      clientMessageId: string,
    ): Promise<boolean> => {
      if (!token || selectedConversationId === null) return false;
      setDraftActionError(null);
      try {
        const result = await knowledgeAgentApi.submitDraftAction(
          token,
          selectedConversationId,
          {
            clientMessageId,
            sourceRunId,
            targetProjectId,
          },
        );
        draftActionRef.current = null;
        setDraftActionPending(false);
        setExtraMessages((previous) => [...previous, result.userMessage]);
        setRunOverrides((previous) => {
          const next = new Map(previous);
          next.set(result.run.id, result.run);
          return next;
        });
        setThreadDrafts((previous) => new Map(previous).set(result.draft.id, result.draft));
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversations(),
        });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        if (classified.kind === "conflict") {
          draftActionRef.current = null;
          setDraftActionPending(false);
          setDraftActionError(
            "已有进行中的回答或整理，请等待完成或取消后再整理。",
          );
          if (selectedConversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(selectedConversationId),
            });
          }
          return false;
        }
        // 结果未知：保留同一幂等键等待重试
        setDraftActionError(classified.message);
        return false;
      }
    },
    [token, selectedConversationId, queryClient],
  );

  const submitDraftAction = useCallback(
    async (
      sourceRunId: number,
      targetProjectId?: number | null,
    ): Promise<boolean> => {
      if (draftActionPending || !token) return false;
      setDraftActionPending(true);
      const action = draftActionRef.current ?? {
        clientMessageId: nextClientMessageId(),
        sourceRunId,
        targetProjectId: targetProjectId ?? null,
      };
      draftActionRef.current = action;
      const submitted = await performDraftAction(
        action.sourceRunId,
        action.targetProjectId,
        action.clientMessageId,
      );
      return submitted;
    },
    [draftActionPending, token, performDraftAction],
  );

  const retryDraftAction = useCallback(async (): Promise<boolean> => {
    const action = draftActionRef.current;
    if (!action || !token || !draftActionPending) return false;
    setDraftActionPending(true);
    return performDraftAction(
      action.sourceRunId,
      action.targetProjectId,
      action.clientMessageId,
    );
  }, [token, draftActionPending, performDraftAction]);

  const editDraft = useCallback(
    async (
      draftId: number,
      fields: KnowledgeDraftEditRequest,
    ): Promise<boolean> => {
      if (!token || draftEditBusy) return false;
      setDraftEditBusy(true);
      setDraftEditError(null);
      try {
        const draft = await knowledgeAgentApi.editDraft(token, draftId, fields);
        setThreadDrafts((previous) => new Map(previous).set(draft.id, draft));
        setDraftEditBusy(false);
        return true;
      } catch (error) {
        setDraftEditBusy(false);
        setDraftEditError(toUserErrorMessage(error));
        return false;
      }
    },
    [token, draftEditBusy],
  );

  const clearDraftEditError = useCallback(() => {
    setDraftEditError(null);
  }, []);

  const confirmDraft = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!token || confirmingDraftId !== null) return false;
      const operationId =
        pendingConfirmsRef.current.get(draftId) ?? nextClientOperationId();
      pendingConfirmsRef.current.set(draftId, operationId);
      setConfirmingDraftId(draftId);
      setDraftConfirmError(null);
      try {
        const result = await knowledgeAgentApi.confirmDraft(token, draftId, {
          clientOperationId: operationId,
        });
        pendingConfirmsRef.current.delete(draftId);
        setConfirmingDraftId(null);
        setThreadDrafts((previous) =>
          new Map(previous).set(result.draft.id, result.draft),
        );
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversations(),
          });
        }
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        setConfirmingDraftId(null);
        if (
          classified.kind === "network" ||
          classified.kind === "server" ||
          classified.kind === "cancelled"
        ) {
          // 结果未知：保留幂等键，提供重试
          setDraftConfirmError(classified.message);
        } else {
          // 409/404 等确定性拒绝：清键并刷新，以服务端 Draft/Candidate 为权威
          pendingConfirmsRef.current.delete(draftId);
          setDraftConfirmError(classified.message);
          if (selectedConversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversations(),
            });
          }
        }
        return false;
      }
    },
    [token, confirmingDraftId, queryClient, selectedConversationId],
  );

  const retryConfirmDraft = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!pendingConfirmsRef.current.has(draftId)) return false;
      return confirmDraft(draftId);
    },
    [confirmDraft],
  );

  const cancelDraft = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!token || draftCancelBusy) return false;
      setDraftCancelBusy(true);
      setDraftCancelError(null);
      try {
        const draft = await knowledgeAgentApi.cancelDraft(token, draftId);
        setThreadDrafts((previous) => new Map(previous).set(draft.id, draft));
        pendingConfirmsRef.current.delete(draftId);
        setDraftCancelBusy(false);
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
        }
        return true;
      } catch (error) {
        setDraftCancelBusy(false);
        // 取消失败独立展示，不写入草稿编辑错误
        setDraftCancelError(toUserErrorMessage(error));
        if (selectedConversationId !== null) {
          // 服务端状态仍是权威：刷新消息页，若已确认会显示回执
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
        }
        return false;
      }
    },
    [token, draftCancelBusy, queryClient, selectedConversationId],
  );

  const clearDraftCancelError = useCallback(() => {
    setDraftCancelError(null);
  }, []);

  const draftByRunId = useCallback(
    (runId: number): KnowledgeCandidateDraft | null => {
      for (const draft of thread.draftsById.values()) {
        if (draft.operationRunId === runId) return draft;
      }
      return null;
    },
    [thread.draftsById],
  );

  const performEntryRevisionAction = useCallback(
    async (
      sourceRunId: number,
      targetEntryId: number,
      instruction: string,
      clientMessageId: string,
    ): Promise<boolean> => {
      if (!token || selectedConversationId === null) return false;
      setRevisionActionError(null);
      try {
        const result = await knowledgeAgentApi.submitEntryRevision(
          token,
          selectedConversationId,
          {
            clientMessageId,
            sourceRunId,
            targetEntryId,
            instruction,
          },
        );
        revisionActionRef.current = null;
        setRevisionActionPending(false);
        setExtraMessages((previous) => [...previous, result.userMessage]);
        setRunOverrides((previous) => {
          const next = new Map(previous);
          next.set(result.run.id, result.run);
          return next;
        });
        setThreadRevisionDrafts((previous) =>
          new Map(previous).set(result.draft.id, result.draft),
        );
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.messages(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
        });
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.conversations(),
        });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        if (classified.kind === "conflict") {
          revisionActionRef.current = null;
          setRevisionActionPending(false);
          setRevisionActionError(
            "已有进行中的回答或修订，请等待完成或取消后再修订。",
          );
          if (selectedConversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(selectedConversationId),
            });
          }
          return false;
        }
        // 结果未知：保留同一幂等键等待重试
        setRevisionActionError(classified.message);
        return false;
      }
    },
    [token, selectedConversationId, queryClient],
  );

  const submitEntryRevision = useCallback(
    async (
      sourceRunId: number,
      targetEntryId: number,
      instruction: string,
    ): Promise<boolean> => {
      const text = instruction.trim();
      if (!text || revisionActionPending || !token) return false;
      setRevisionActionPending(true);
      const action = revisionActionRef.current ?? {
        clientMessageId: nextClientMessageId(),
        sourceRunId,
        targetEntryId,
        instruction: text,
      };
      revisionActionRef.current = action;
      const submitted = await performEntryRevisionAction(
        action.sourceRunId,
        action.targetEntryId,
        action.instruction,
        action.clientMessageId,
      );
      return submitted;
    },
    [revisionActionPending, token, performEntryRevisionAction],
  );

  const retryEntryRevision = useCallback(async (): Promise<boolean> => {
    const action = revisionActionRef.current;
    if (!action || !token || !revisionActionPending) return false;
    return performEntryRevisionAction(
      action.sourceRunId,
      action.targetEntryId,
      action.instruction,
      action.clientMessageId,
    );
  }, [token, revisionActionPending, performEntryRevisionAction]);

  const editEntryRevision = useCallback(
    async (
      draftId: number,
      fields: KnowledgeRevisionEditRequest,
    ): Promise<boolean> => {
      if (!token || revisionEditBusy) return false;
      setRevisionEditBusy(true);
      setRevisionEditError(null);
      try {
        const draft = await knowledgeAgentApi.editEntryRevisionDraft(
          token,
          draftId,
          fields,
        );
        setThreadRevisionDrafts((previous) =>
          new Map(previous).set(draft.id, draft),
        );
        setRevisionEditBusy(false);
        return true;
      } catch (error) {
        setRevisionEditBusy(false);
        setRevisionEditError(toUserErrorMessage(error));
        return false;
      }
    },
    [token, revisionEditBusy],
  );

  const clearRevisionEditError = useCallback(() => {
    setRevisionEditError(null);
  }, []);

  const confirmEntryRevision = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!token || confirmingRevisionDraftId !== null) return false;
      const operationId =
        pendingRevisionConfirmsRef.current.get(draftId) ??
        nextClientOperationId();
      pendingRevisionConfirmsRef.current.set(draftId, operationId);
      setConfirmingRevisionDraftId(draftId);
      setRevisionConfirmError(null);
      try {
        const result = await knowledgeAgentApi.confirmEntryRevision(
          token,
          draftId,
          { clientOperationId: operationId },
        );
        pendingRevisionConfirmsRef.current.delete(draftId);
        setConfirmingRevisionDraftId(null);
        setRevisionConfirmRetryable(false);
        setThreadRevisionDrafts((previous) =>
          new Map(previous).set(result.draft.id, result.draft),
        );
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversations(),
          });
        }
        // 正式知识已更新：相关查询失效（引用详情/项目知识由后续消息页恢复）
        void queryClient.invalidateQueries({ queryKey: ["projects"] });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        setConfirmingRevisionDraftId(null);
        if (
          classified.kind === "network" ||
          classified.kind === "server" ||
          classified.kind === "cancelled"
        ) {
          // 结果未知：保留幂等键，提供重试
          setRevisionConfirmError(classified.message);
          setRevisionConfirmRetryable(true);
        } else {
          // 409/404 等确定性拒绝：清键并刷新，以服务端 Draft/Execution 为权威
          pendingRevisionConfirmsRef.current.delete(draftId);
          setRevisionConfirmError(classified.message);
          setRevisionConfirmRetryable(false);
          if (selectedConversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversations(),
            });
          }
        }
        return false;
      }
    },
    [token, confirmingRevisionDraftId, queryClient, selectedConversationId],
  );

  const retryConfirmEntryRevision = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!pendingRevisionConfirmsRef.current.has(draftId)) return false;
      return confirmEntryRevision(draftId);
    },
    [confirmEntryRevision],
  );

  const undoEntryRevision = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!token || undoingRevisionDraftId !== null) return false;
      const operationId =
        pendingRevisionUndoRef.current.get(draftId) ?? nextClientOperationId();
      pendingRevisionUndoRef.current.set(draftId, operationId);
      setUndoingRevisionDraftId(draftId);
      setRevisionUndoError(null);
      setRevisionUndoErrorDraftId(null);
      try {
        const result = await knowledgeAgentApi.undoEntryRevision(
          token,
          draftId,
          { clientOperationId: operationId },
        );
        pendingRevisionUndoRef.current.delete(draftId);
        setUndoingRevisionDraftId(null);
        setRevisionUndoRetryable(false);
        setRevisionUndoErrorDraftId(null);
        setThreadRevisionDrafts((previous) =>
          new Map(previous).set(result.draft.id, result.draft),
        );
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
          });
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.conversations(),
          });
        }
        void queryClient.invalidateQueries({ queryKey: ["projects"] });
        return true;
      } catch (error) {
        const classified = classifyKnowledgeAgentError(error);
        setUndoingRevisionDraftId(null);
        if (
          classified.kind === "network" ||
          classified.kind === "server" ||
          classified.kind === "cancelled"
        ) {
          // 结果未知：保留撤销幂等键，提供重试
          setRevisionUndoError(classified.message);
          setRevisionUndoRetryable(true);
          setRevisionUndoErrorDraftId(draftId);
        } else {
          pendingRevisionUndoRef.current.delete(draftId);
          setRevisionUndoError(classified.message);
          setRevisionUndoRetryable(false);
          setRevisionUndoErrorDraftId(draftId);
          if (selectedConversationId !== null) {
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.messages(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversation(selectedConversationId),
            });
            void queryClient.invalidateQueries({
              queryKey: knowledgeAgentKeys.conversations(),
            });
          }
        }
        return false;
      }
    },
    [token, undoingRevisionDraftId, queryClient, selectedConversationId],
  );

  const retryUndoEntryRevision = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!pendingRevisionUndoRef.current.has(draftId)) return false;
      return undoEntryRevision(draftId);
    },
    [undoEntryRevision],
  );

  const cancelEntryRevision = useCallback(
    async (draftId: number): Promise<boolean> => {
      if (!token || revisionCancelBusy) return false;
      setRevisionCancelBusy(true);
      setRevisionCancelError(null);
      try {
        const draft = await knowledgeAgentApi.cancelEntryRevisionDraft(
          token,
          draftId,
        );
        setThreadRevisionDrafts((previous) =>
          new Map(previous).set(draft.id, draft),
        );
        pendingRevisionConfirmsRef.current.delete(draftId);
        pendingRevisionUndoRef.current.delete(draftId);
        setRevisionCancelBusy(false);
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
        }
        return true;
      } catch (error) {
        setRevisionCancelBusy(false);
        setRevisionCancelError(toUserErrorMessage(error));
        if (selectedConversationId !== null) {
          void queryClient.invalidateQueries({
            queryKey: knowledgeAgentKeys.messages(selectedConversationId),
          });
        }
        return false;
      }
    },
    [token, revisionCancelBusy, queryClient, selectedConversationId],
  );

  const clearRevisionCancelError = useCallback(() => {
    setRevisionCancelError(null);
  }, []);

  const revisionDraftByRunId = useCallback(
    (runId: number): KnowledgeEntryRevisionDraft | null => {
      for (const draft of thread.revisionDraftsById.values()) {
        if (draft.operationRunId === runId) return draft;
      }
      return null;
    },
    [thread.revisionDraftsById],
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
          projectName: scope.projectName ?? undefined,
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
    setEntryResultsByRun(new Map());
    setExtraMessages([]);
    setThreadDrafts(new Map());
    setThreadRevisionDrafts(new Map());
    setPending(null);
    setSubmitError(null);
    setDraftActionPending(false);
    setDraftActionError(null);
    draftActionRef.current = null;
    pendingConfirmsRef.current = new Map();
    setConfirmingDraftId(null);
    setDraftConfirmError(null);
    setDraftEditError(null);
    setDraftCancelError(null);
    setRevisionActionPending(false);
    setRevisionActionError(null);
    revisionActionRef.current = null;
    pendingRevisionConfirmsRef.current = new Map();
    pendingRevisionUndoRef.current = new Map();
    setConfirmingRevisionDraftId(null);
    setRevisionConfirmError(null);
    setRevisionConfirmRetryable(false);
    setUndoingRevisionDraftId(null);
    setRevisionUndoError(null);
    setRevisionUndoRetryable(false);
    setRevisionUndoErrorDraftId(null);
    setRevisionEditError(null);
    setRevisionCancelError(null);
    setModesState(DEFAULT_MODES);
    setScopeError(null);
    setCancelError(null);
    setExplicitChoice(conversationId);
  }, []);

  const startNewConversation = useCallback(() => {
    setOlderPages([]);
    setRunOverrides(new Map());
    setEntryResultsByRun(new Map());
    setExtraMessages([]);
    setThreadDrafts(new Map());
    setThreadRevisionDrafts(new Map());
    setPending(null);
    setSubmitError(null);
    setDraftActionPending(false);
    setDraftActionError(null);
    draftActionRef.current = null;
    pendingConfirmsRef.current = new Map();
    setConfirmingDraftId(null);
    setDraftConfirmError(null);
    setDraftEditError(null);
    setDraftCancelError(null);
    setRevisionActionPending(false);
    setRevisionActionError(null);
    revisionActionRef.current = null;
    pendingRevisionConfirmsRef.current = new Map();
    pendingRevisionUndoRef.current = new Map();
    setConfirmingRevisionDraftId(null);
    setRevisionConfirmError(null);
    setRevisionConfirmRetryable(false);
    setUndoingRevisionDraftId(null);
    setRevisionUndoError(null);
    setRevisionUndoRetryable(false);
    setRevisionUndoErrorDraftId(null);
    setRevisionEditError(null);
    setRevisionCancelError(null);
    setModesState(DEFAULT_MODES);
    setScopeError(null);
    setCancelError(null);
    setExplicitChoice("draft");
  }, []);

  const cancelMutation = useMutation({
    mutationFn: (runId: number) =>
      knowledgeAgentApi.cancelRun(token as string, runId),
  });

  const requestCancelRun = useCallback(() => {
    if (!activeRunId) return;
    setCancelError(null);
    void cancelMutation
      .mutateAsync(activeRunId)
      .then(() => {
        void queryClient.invalidateQueries({
          queryKey: knowledgeAgentKeys.run(activeRunId),
        });
      })
      .catch((error) => {
        // 取消失败保留在 Run 卡，用户可原操作重试。
        setCancelError({ runId: activeRunId, message: toUserErrorMessage(error) });
      });
  }, [activeRunId, cancelMutation, queryClient]);

  const setContextMode = useCallback((mode: ContextMode) => {
    setModesState((previous) => withContextMode(previous, mode));
  }, []);
  const setAnswerMode = useCallback((mode: AnswerMode) => {
    setModesState((previous) => withAnswerMode(previous, mode));
  }, []);
  const setResultMode = useCallback((mode: ResultMode) => {
    setModesState((previous) => withResultMode(previous, mode));
  }, []);
  const setModes = (next: ModeSelection) => {
    setModesState({ ...next });
  };

  /** 按 Run 读取/派生结果分页状态；未初始化时从快照首屏派生。 */
  const entryResultsForRun = useCallback(
    (runId: number): EntryResultsState | null => {
      const stored = entryResultsByRun.get(runId);
      if (stored) return stored;
      const run = thread.runsById.get(runId);
      const snapshot = run?.entryResult ?? null;
      if (!snapshot) return null;
      const items = snapshot.items.slice(0, ENTRY_RESULT_PAGE_SIZE);
      return {
        runId,
        items,
        nextCursor: null,
        hasMore: snapshot.items.length > ENTRY_RESULT_PAGE_SIZE,
        loadingMore: false,
        error: null,
        primed: false,
      };
    },
    [entryResultsByRun, thread.runsById],
  );

  const updateEntryResults = useCallback(
    (runId: number, update: (state: EntryResultsState) => EntryResultsState) => {
      setEntryResultsByRun((previous) => {
        const current = previous.get(runId) ?? emptyEntryResultsState(runId);
        const next = new Map(previous);
        next.set(runId, update(current));
        return next;
      });
    },
    [],
  );

  /** 首次加载：用服务端第一页取得不透明游标（内容与快照首屏一致，按 id 去重）。 */
  const primeEntryResults = useCallback(
    (runId: number) => {
      if (!token) return;
      const current = entryResultsByRun.get(runId);
      if (current?.primed || current?.loadingMore) return;
      updateEntryResults(runId, (state) => ({ ...state, loadingMore: true, error: null }));
      void knowledgeAgentApi
        .getEntryResults(token, runId, null, ENTRY_RESULT_PAGE_SIZE)
        .then((page) => {
          updateEntryResults(runId, (state) => ({
            ...state,
            items: mergeEntryItems(state.items, page.items),
            nextCursor: page.nextCursor,
            hasMore: page.hasMore,
            loadingMore: false,
            error: null,
            primed: true,
          }));
        })
        .catch((error) => {
          updateEntryResults(runId, (state) => ({
            ...state,
            loadingMore: false,
            error: toUserErrorMessage(error),
            primed: true,
          }));
        });
    },
    [token, entryResultsByRun, updateEntryResults],
  );

  /** 加载下一页：只读同一快照，不重新提交问题；失败保留已加载项。 */
  const loadMoreEntryResults = useCallback(
    (runId: number) => {
      if (!token) return;
      const current = entryResultsByRun.get(runId);
      if (!current || current.loadingMore) return;
      if (!current.primed) {
        primeEntryResults(runId);
        return;
      }
      if (!current.nextCursor || !current.hasMore) return;
      updateEntryResults(runId, (state) => ({ ...state, loadingMore: true, error: null }));
      void knowledgeAgentApi
        .getEntryResults(token, runId, current.nextCursor, ENTRY_RESULT_PAGE_SIZE)
        .then((page) => {
          updateEntryResults(runId, (state) => ({
            ...state,
            items: mergeEntryItems(state.items, page.items),
            nextCursor: page.nextCursor,
            hasMore: page.hasMore,
            loadingMore: false,
            error: null,
          }));
        })
        .catch((error) => {
          updateEntryResults(runId, (state) => ({
            ...state,
            loadingMore: false,
            error: toUserErrorMessage(error),
          }));
        });
    },
    [token, entryResultsByRun, primeEntryResults, updateEntryResults],
  );

  const retryEntryResults = useCallback(
    (runId: number) => {
      const current = entryResultsByRun.get(runId);
      if (!current || current.loadingMore) return;
      if (!current.primed || !current.nextCursor) {
        // 首屏或游标获取失败：重置后重新拉取第一页
        updateEntryResults(runId, (state) => ({ ...state, primed: false, error: null }));
        primeEntryResults(runId);
        return;
      }
      loadMoreEntryResults(runId);
    },
    [entryResultsByRun, primeEntryResults, loadMoreEntryResults, updateEntryResults],
  );

  return {
    initialLoading: conversationsQuery.isLoading,
    conversations,
    conversationsError: conversationsQuery.isError
      ? toUserErrorMessage(conversationsQuery.error)
      : null,
    activeConversation,
    activeConversationLoading: activeConversationQuery.isLoading,
    isDraft,
    userInitiatedDraft: explicitChoice === "draft",
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
    setResultMode,
    setModes,
    entryResultsForRun,
    primeEntryResults,
    loadMoreEntryResults,
    retryEntryResults,
    submit,
    retrySubmit,
    retryRun,
    draftsById: thread.draftsById,
    draftByRunId,
    submitDraftAction,
    draftActionPending,
    draftActionError,
    retryDraftAction,
    editDraft,
    clearDraftEditError,
    draftEditBusy,
    draftEditError,
    confirmDraft,
    retryConfirmDraft,
    confirmingDraftId,
    draftConfirmError,
    cancelDraft,
    draftCancelBusy,
    draftCancelError,
    clearDraftCancelError,
    revisionDraftsById: thread.revisionDraftsById,
    revisionDraftByRunId,
    submitEntryRevision,
    revisionActionPending,
    revisionActionError,
    retryEntryRevision,
    editEntryRevision,
    clearRevisionEditError,
    revisionEditBusy,
    revisionEditError,
    confirmEntryRevision,
    retryConfirmEntryRevision,
    confirmingRevisionDraftId,
    revisionConfirmError,
    revisionConfirmRetryable,
    undoEntryRevision,
    retryUndoEntryRevision,
    undoingRevisionDraftId,
    revisionUndoError,
    revisionUndoRetryable,
    revisionUndoErrorDraftId,
    cancelEntryRevision,
    revisionCancelBusy,
    revisionCancelError,
    clearRevisionCancelError,
    activeRun,
    runPolling: Boolean(runQuery.data && isRunActive(runQuery.data.status)),
    runPollingError: runQuery.isError
      ? toUserErrorMessage(runQuery.error)
      : null,
    retryRunPolling: () => {
      void runQuery.refetch();
    },
    cancelling: cancelMutation.isPending || Boolean(activeRun?.cancelRequested),
    cancelError:
      cancelError?.runId === activeRun?.id ? (cancelError?.message ?? null) : null,
    requestCancelRun,
    appActive,
  };
}
