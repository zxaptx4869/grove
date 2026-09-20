import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { useQuery } from "@tanstack/react-query";

import { getProjects } from "@/src/api";
import { useAuth } from "@/src/auth";
import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AnswerCard } from "@/src/knowledge-agent/components/AnswerCard";
import { Composer } from "@/src/knowledge-agent/components/Composer";
import {
  EntryDetailSheet,
  type EntryDetailTarget,
} from "@/src/knowledge-agent/components/EntryDetailSheet";
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import { ModeSheet } from "@/src/knowledge-agent/components/ModeSheet";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { RichText } from "@/src/knowledge-agent/components/RichText";
import { ScopeSheet } from "@/src/knowledge-agent/components/ScopeSheet";
import { toUserErrorMessage } from "@/src/knowledge-agent/errors";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import type {
  KnowledgeConversation,
  KnowledgeMessage,
  KnowledgeRun,
  KnowledgeScopeChangeRequest,
} from "@/src/knowledge-agent/types";
import { isRunActive } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

function scopeLabel(scopeType: string, projectName?: string | null): string {
  return scopeType === "project" ? projectName ?? "项目" : "全部知识";
}

export function ConversationScreen() {
  const { token } = useAuth();
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const controller = useConversationController(token);
  const scrollRef = useRef<ScrollView>(null);
  const contentHeightRef = useRef(0);
  const scrollYRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const olderAnchorRef = useRef<{ contentHeight: number; scrollY: number } | null>(null);
  const positionedConversationRef = useRef<string | null>(null);
  const layoutConversationRef = useRef<string | null>(null);
  const followNextContentRef = useRef(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [scopeRecoveryNotice, setScopeRecoveryNotice] = useState<string | null>(null);
  const [modeOpen, setModeOpen] = useState(false);
  const [entryDetail, setEntryDetail] = useState<EntryDetailTarget | null>(null);
  const closeEntryDetail = useCallback(() => setEntryDetail(null), []);
  const projectsQuery = useQuery({
    queryKey: ["projects", "mobile-scope"],
    queryFn: () => getProjects(token as string),
    enabled: Boolean(
      token &&
        (scopeOpen ||
          (controller.isDraft && controller.currentScope.scopeType === "project")),
    ),
  });

  useEffect(() => {
    if (
      !controller.isDraft ||
      controller.currentScope.scopeType !== "project" ||
      controller.currentScope.projectId === null ||
      projectsQuery.isLoading ||
      projectsQuery.isError ||
      !projectsQuery.data
    ) {
      return;
    }
    const projectStillAvailable = projectsQuery.data.some(
      (project) => project.id === controller.currentScope.projectId,
    );
    if (projectStillAvailable) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setScopeRecoveryNotice("上次使用的项目已不可用，已切换为全部知识。");
      void controller.changeScope({ scopeType: "workspace", projectId: null });
    });
    return () => {
      cancelled = true;
    };
  }, [controller, projectsQuery.data, projectsQuery.isError, projectsQuery.isLoading]);

  const validatingRestoredProject =
    controller.isDraft &&
    controller.currentScope.scopeType === "project" &&
    projectsQuery.isLoading;
  const restoredProjectValidationError =
    controller.isDraft &&
    controller.currentScope.scopeType === "project" &&
    projectsQuery.isError;

  const runByAssistantMessage = useMemo(() => {
    const map = new Map<number, KnowledgeRun>();
    for (const run of controller.thread.runsById.values()) {
      if (run.assistantMessageId !== null) map.set(run.assistantMessageId, run);
    }
    return map;
  }, [controller.thread.runsById]);

  const conversationKey = controller.isDraft
    ? "draft"
    : String(controller.activeConversation?.id ?? "restoring");
  const initialPositionReady =
    !controller.initialLoading &&
    !controller.activeConversationLoading &&
    !controller.messagesLoading;
  const threadHasMessages = controller.thread.items.length > 0;

  const scheduleInitialPosition = useCallback(() => {
    if (
      !initialPositionReady ||
      !threadHasMessages ||
      layoutConversationRef.current !== conversationKey ||
      positionedConversationRef.current === conversationKey
    ) {
      return false;
    }
    const savedOffset = controller.getReadingPosition(conversationKey);
    if (savedOffset === null) {
      scrollRef.current?.scrollToEnd({ animated: false });
      stickToBottomRef.current = true;
    } else {
      scrollRef.current?.scrollTo({ y: savedOffset, animated: false });
      stickToBottomRef.current = false;
    }
    positionedConversationRef.current = conversationKey;
    followNextContentRef.current = false;
    return true;
  }, [controller, conversationKey, initialPositionReady, threadHasMessages]);

  useEffect(() => {
    scheduleInitialPosition();
  }, [scheduleInitialPosition]);

  const handleSend = async () => {
    const value = controller.input.trim();
    if (!value) return;
    stickToBottomRef.current = true;
    followNextContentRef.current = true;
    scrollRef.current?.scrollToEnd({ animated: true });
    await controller.submit(value);
  };

  const handleScopeChange = async (scope: KnowledgeScopeChangeRequest) => {
    setScopeRecoveryNotice(null);
    await controller.changeScope(scope);
    setScopeOpen(false);
  };

  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    scrollYRef.current = contentOffset.y;
    controller.setReadingPosition(conversationKey, contentOffset.y);
    contentHeightRef.current = contentSize.height;
    const distanceFromBottom = contentSize.height - contentOffset.y - layoutMeasurement.height;
    stickToBottomRef.current = distanceFromBottom < 80;
  };

  const handleContentSizeChange = (_width: number, height: number) => {
    const olderAnchor = olderAnchorRef.current;
    if (olderAnchor && height > olderAnchor.contentHeight) {
      scrollRef.current?.scrollTo({
        y: olderAnchor.scrollY + height - olderAnchor.contentHeight,
        animated: false,
      });
      olderAnchorRef.current = null;
      contentHeightRef.current = height;
      return;
    }
    contentHeightRef.current = height;
    layoutConversationRef.current = conversationKey;
    if (scheduleInitialPosition()) return;
    if (followNextContentRef.current || stickToBottomRef.current) {
      scrollRef.current?.scrollToEnd({ animated: true });
      followNextContentRef.current = false;
    }
  };

  const handleLoadOlder = async () => {
    olderAnchorRef.current = {
      contentHeight: contentHeightRef.current,
      scrollY: scrollYRef.current,
    };
    stickToBottomRef.current = false;
    await controller.loadOlderMessages();
    requestAnimationFrame(() => {
      olderAnchorRef.current = null;
    });
  };

  const showInitialError =
    controller.conversationsError !== null && !controller.userInitiatedDraft;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.root}>
        <View style={styles.header}>
          <View style={styles.brandSlot} accessibilityLabel="Grove">
            <View style={styles.brandMark}>
              <Text style={styles.brandText}>G</Text>
            </View>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`修改当前知识范围，当前为${controller.scopeLabel}`}
            onPress={() => setScopeOpen(true)}
            style={({ pressed }) => [styles.scopeButton, pressed && styles.pressed]}
          >
            <Text style={styles.scopeButtonText} numberOfLines={1}>
              {controller.scopeLabel}
            </Text>
            <AgentIcon name="down" size={14} color={theme.muted} />
          </Pressable>
          <HistoryControl
            conversations={controller.conversations}
            activeConversationId={
              controller.isDraft ? null : controller.activeConversation?.id ?? null
            }
            loading={controller.conversationsLoading}
            error={controller.conversationsError}
            onRetry={controller.retryConversations}
            onSelect={(id) => {
              if (!controller.pending) {
                controller.clearReadingPosition(String(id));
                stickToBottomRef.current = true;
                layoutConversationRef.current = null;
                positionedConversationRef.current = null;
              }
              controller.switchToConversation(id);
            }}
            onNew={() => {
              if (!controller.pending) {
                controller.clearReadingPosition("draft");
                stickToBottomRef.current = true;
                layoutConversationRef.current = null;
                positionedConversationRef.current = null;
              }
              controller.startNewConversation();
            }}
          />
        </View>

        <ScrollView
          ref={scrollRef}
          style={styles.thread}
          contentContainerStyle={styles.threadContent}
          keyboardShouldPersistTaps="handled"
          scrollEventThrottle={16}
          accessibilityLabel="知识 Agent 对话"
          onScroll={handleScroll}
          onContentSizeChange={handleContentSizeChange}
        >
          {controller.thread.hasMore ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="加载更早消息"
              disabled={controller.loadingOlder}
              onPress={() => void handleLoadOlder()}
              style={({ pressed }) => [styles.loadOlder, pressed && styles.pressed]}
            >
              {controller.loadingOlder ? <ActivityIndicator color={theme.green} /> : null}
              <Text style={styles.loadOlderText}>
                {controller.loadingOlder ? "正在加载…" : "加载更早消息"}
              </Text>
            </Pressable>
          ) : null}

          {controller.initialLoading || controller.activeConversationLoading ? (
            <View style={styles.centerState}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.stateCopy}>正在恢复知识对话…</Text>
            </View>
          ) : controller.recoveryError ? (
            <View style={styles.centerState} accessibilityRole="alert">
              <Text style={styles.errorTitle}>未能恢复上次移动任务</Text>
              <Text style={styles.stateCopy}>{controller.recoveryError}</Text>
              <View style={styles.recoveryActions}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="重试恢复移动任务"
                  onPress={controller.retryRecovery}
                  style={styles.retryButton}
                >
                  <AgentIcon name="retry" size={16} color={theme.green} />
                  <Text style={styles.retryText}>重试恢复</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="退出恢复并进入新对话"
                  onPress={() => void controller.exitRecovery()}
                  style={styles.retryButton}
                >
                  <Text style={styles.retryText}>退出恢复</Text>
                </Pressable>
              </View>
            </View>
          ) : showInitialError ? (
            <View style={styles.centerState}>
              <Text style={styles.errorTitle}>对话读取失败</Text>
              <Text style={styles.stateCopy}>{controller.conversationsError}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重试读取对话"
                onPress={controller.retryConversations}
                style={styles.retryButton}
              >
                <AgentIcon name="retry" size={16} color={theme.green} />
                <Text style={styles.retryText}>重试</Text>
              </Pressable>
            </View>
          ) : controller.messagesError ? (
            <View style={styles.centerState}>
              <Text style={styles.errorTitle}>消息读取失败</Text>
              <Text style={styles.stateCopy}>{controller.messagesError}</Text>
            </View>
          ) : controller.thread.items.length === 0 ? (
            <View style={styles.emptyState}>
              <View style={styles.agentMark}>
                <AgentIcon name="message" size={24} color={theme.ai} />
              </View>
              <Text style={styles.emptyTitle}>从一个问题开始</Text>
              <Text style={styles.emptyCopy}>
                当前范围是{controller.scopeLabel}。回答会按正式 Agent 结果原样展示。
              </Text>
            </View>
          ) : null}

          {controller.olderError ? (
            <View style={styles.inlineError}>
              <Text style={styles.errorTitle}>更早消息加载失败</Text>
              <Text style={styles.stateCopy}>{controller.olderError}</Text>
            </View>
          ) : null}

          {scopeRecoveryNotice ? (
            <View style={styles.inlineNotice} accessibilityRole="alert">
              <Text style={styles.stateCopy}>{scopeRecoveryNotice}</Text>
            </View>
          ) : null}

          {restoredProjectValidationError ? (
            <View style={styles.inlineError} accessibilityRole="alert">
              <Text style={styles.errorTitle}>上次的知识范围暂时无法确认</Text>
              <Text style={styles.stateCopy}>
                可重试确认，或打开顶部范围切换为全部知识。
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重试确认上次知识范围"
                onPress={() => void projectsQuery.refetch()}
                style={styles.retryButton}
              >
                <AgentIcon name="retry" size={16} color={theme.green} />
                <Text style={styles.retryText}>重试确认</Text>
              </Pressable>
            </View>
          ) : null}

          {controller.thread.items.map((message) => (
            <ThreadMessage
              key={message.id}
              message={message}
              run={
                message.role === "assistant"
                  ? runByAssistantMessage.get(message.id) ??
                    (message.runId !== null
                      ? controller.thread.runsById.get(message.runId) ?? null
                      : null)
                  : null
              }
              activeRun={controller.activeRun}
              resumableRunId={controller.resumableRunId}
              cancelling={controller.cancelling}
              pollingError={controller.runPollingError}
              cancelError={controller.cancelError}
              onCancel={() => void controller.requestCancelRun()}
              onRetryPolling={controller.retryRunPolling}
              onContinue={(runId) => void controller.continueRun(runId)}
              onRetry={(runId) => void controller.retryRun(runId)}
              onOpenEntry={setEntryDetail}
            />
          ))}

          {controller.pending && controller.submitting ? (
            <View style={styles.pendingMessage} accessibilityRole="progressbar">
              <Text style={styles.pendingContext}>
                {controller.pending.contextMode === "continue"
                  ? "继续当前主题"
                  : controller.pending.contextMode === "new_topic"
                    ? "新话题"
                    : "正在发送"}
              </Text>
              <View style={[styles.userBubble, styles.pendingBubble]}>
                <Text style={styles.userText}>{controller.pending.text}</Text>
              </View>
            </View>
          ) : controller.pending && controller.conversationCreationUnknown ? (
            <View style={styles.pendingBox} accessibilityRole="alert">
              <Text style={styles.pendingTitle}>新对话创建结果无法确认</Text>
              <Text style={styles.stateCopy}>
                当前接口无法安全重试创建步骤。为避免重复会话，本次不会自动重发。
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="放弃本次恢复并返回新对话"
                onPress={() => void controller.exitRecovery()}
                style={styles.retryButton}
              >
                <Text style={styles.retryText}>返回新对话</Text>
              </Pressable>
            </View>
          ) : controller.pending && controller.submissionResultUnknown ? (
            <View style={styles.pendingBox}>
              <Text style={styles.pendingTitle}>消息提交结果尚未确认</Text>
              <Text style={styles.stateCopy}>{controller.pending.text}</Text>
              {controller.submitError ? (
                <Text style={styles.pendingError}>{controller.submitError}</Text>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="使用同一标识重试提交"
                disabled={controller.submitting}
                onPress={() => void controller.retrySubmit()}
                style={styles.retryButton}
              >
                <AgentIcon name="retry" size={16} color={theme.green} />
                <Text style={styles.retryText}>恢复这次提交</Text>
              </Pressable>
            </View>
          ) : controller.submitError ? (
            <View style={styles.inlineError} accessibilityRole="alert">
              <Text style={styles.errorTitle}>消息未发送</Text>
              <Text style={styles.stateCopy}>{controller.submitError}</Text>
            </View>
          ) : null}

          {controller.scopeError ? (
            <View style={styles.inlineError} accessibilityRole="alert">
              <Text style={styles.errorTitle}>范围未切换</Text>
              <Text style={styles.stateCopy}>{controller.scopeError}</Text>
            </View>
          ) : null}

          {controller.persistenceError ? (
            <View style={styles.inlineError} accessibilityRole="alert">
              <Text style={styles.errorTitle}>移动任务状态未保存</Text>
              <Text style={styles.stateCopy}>{controller.persistenceError}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重试保存移动任务状态"
                onPress={controller.retryPersistence}
                style={styles.retryButton}
              >
                <AgentIcon name="retry" size={16} color={theme.green} />
                <Text style={styles.retryText}>重试保存</Text>
              </Pressable>
            </View>
          ) : null}
        </ScrollView>

        <View style={{ paddingBottom: keyboardHeight }}>
          <Composer
            value={controller.input}
            onChangeText={controller.setInput}
            onSend={() => void handleSend()}
            modes={controller.modes}
            onOpenModes={() => setModeOpen(true)}
            onRemoveContextOverride={() => controller.setContextMode("auto")}
            submitting={controller.pending !== null}
            disabled={
              controller.initialLoading ||
              controller.activeRun !== null ||
              controller.submitting ||
              controller.recoveryError !== null ||
              controller.conversationCreationUnknown ||
              validatingRestoredProject ||
              restoredProjectValidationError ||
              (controller.conversationsError !== null && !controller.userInitiatedDraft)
            }
          />
        </View>
      </View>

      <ScopeSheet
        visible={scopeOpen}
        current={controller.currentScope}
        projects={projectsQuery.data}
        loadingProjects={projectsQuery.isLoading}
        projectsError={projectsQuery.isError ? toUserErrorMessage(projectsQuery.error) : null}
        disabled={controller.activeRun !== null || controller.scopeBusy}
        disabledNote={
          controller.activeRun !== null
            ? "正在回答中，完成或取消当前回答后再切换范围。"
            : null
        }
        onChange={(scope) => void handleScopeChange(scope)}
        onClose={() => setScopeOpen(false)}
      />
      <ModeSheet
        visible={modeOpen}
        modes={controller.modes}
        onChange={controller.setModes}
        onClose={() => setModeOpen(false)}
      />
      <EntryDetailSheet target={entryDetail} onClose={closeEntryDetail} />
    </SafeAreaView>
  );
}

const HistoryControl = memo(function HistoryControl({
  conversations,
  activeConversationId,
  loading,
  error,
  onRetry,
  onSelect,
  onNew,
}: {
  conversations: KnowledgeConversation[] | undefined;
  activeConversationId: number | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onSelect: (conversationId: number) => void;
  onNew: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="打开对话历史"
        onPress={() => setOpen(true)}
        style={({ pressed }) => [styles.historyButton, pressed && styles.pressed]}
      >
        <AgentIcon name="history" size={21} color={theme.ink} />
      </Pressable>
      <HistorySheet
        visible={open}
        conversations={conversations}
        activeConversationId={activeConversationId}
        loading={loading}
        error={error}
        onRetry={onRetry}
        onSelect={(id) => {
          onSelect(id);
          setOpen(false);
        }}
        onNew={() => {
          onNew();
          setOpen(false);
        }}
        onClose={() => setOpen(false)}
      />
    </>
  );
});

function ThreadMessage({
  message,
  run,
  activeRun,
  resumableRunId,
  cancelling,
  pollingError,
  cancelError,
  onCancel,
  onRetryPolling,
  onContinue,
  onRetry,
  onOpenEntry,
}: {
  message: KnowledgeMessage;
  run: KnowledgeRun | null;
  activeRun: KnowledgeRun | null;
  resumableRunId: number | null;
  cancelling: boolean;
  pollingError: string | null;
  cancelError: string | null;
  onCancel: () => void;
  onRetryPolling: () => void;
  onContinue: (runId: number) => void;
  onRetry: (runId: number) => void;
  onOpenEntry: (target: EntryDetailTarget) => void;
}) {
  if (message.messageType === "scope_change") {
    return (
      <View style={styles.scopeDivider}>
        <View style={styles.scopeLine} />
        <Text style={styles.scopeEvent}>{message.content}</Text>
        <View style={styles.scopeLine} />
      </View>
    );
  }
  if (message.role === "user") {
    return (
      <View style={styles.userMessage}>
        {message.requestContextMode && message.requestContextMode !== "auto" ? (
          <Text style={styles.contextTag}>
            {message.requestContextMode === "continue" ? "继续当前主题" : "新话题"}
          </Text>
        ) : null}
        <View style={styles.userBubble}>
          <Text style={styles.userText}>{message.content}</Text>
        </View>
      </View>
    );
  }
  const runScope = run
    ? scopeLabel(run.scopeType, run.projectName)
    : scopeLabel(message.scopeType, message.projectName);
  return (
    <View style={styles.assistantMessage}>
      <View style={styles.agentLabel}>
        <View style={styles.agentDot}>
          <Text style={styles.agentDotText}>G</Text>
        </View>
        <Text style={styles.agentLabelText}>知识 Agent</Text>
      </View>
      {!run ? (
        message.content.trim() ? (
          <View style={styles.legacyAnswer}>
            <RichText>{message.content}</RichText>
          </View>
        ) : null
      ) : isRunActive(run.status) ? (
        <ProcessCard
          run={run}
          cancelling={cancelling && activeRun?.id === run.id}
          pollingError={activeRun?.id === run.id ? pollingError : null}
          cancelError={activeRun?.id === run.id ? cancelError : null}
          onCancel={onCancel}
          onRetryPolling={onRetryPolling}
        />
      ) : (
        <AnswerCard
          run={run}
          scopeLabel={runScope}
          canContinue={resumableRunId === run.id}
          onContinue={() => onContinue(run.id)}
          onRetry={() => onRetry(run.id)}
          onOpenEntry={onOpenEntry}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: theme.bg },
  root: { flex: 1, backgroundColor: theme.bg },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
  brandSlot: { width: 58, alignItems: "flex-start" },
  brandMark: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.green,
  },
  brandText: { color: "#FFFFFF", fontSize: 14, fontWeight: "700" },
  scopeButton: {
    flex: 1,
    maxWidth: 220,
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    paddingHorizontal: 5,
    borderRadius: 8,
  },
  scopeButtonText: { flexShrink: 1, color: theme.ink, fontSize: 15, fontWeight: "700" },
  historyButton: {
    width: 58,
    height: 44,
    alignItems: "center",
    justifyContent: "flex-end",
  },
  thread: { flex: 1 },
  threadContent: { padding: 12, paddingBottom: 20 },
  loadOlder: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    marginBottom: 12,
  },
  loadOlderText: { color: theme.green, fontSize: 12, fontWeight: "600" },
  centerState: { alignItems: "center", gap: 9, paddingVertical: 42, paddingHorizontal: 24 },
  stateCopy: { color: theme.muted, fontSize: 12, lineHeight: 20, textAlign: "center" },
  errorTitle: { color: theme.error, fontSize: 13, fontWeight: "700" },
  retryButton: {
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  retryText: { color: theme.green, fontSize: 12, fontWeight: "700" },
  recoveryActions: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  emptyState: { alignItems: "center", paddingVertical: 48, paddingHorizontal: 28 },
  agentMark: {
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 12,
    backgroundColor: theme.aiSoft,
  },
  emptyTitle: { marginTop: 14, color: theme.ink, fontSize: 16, fontWeight: "700" },
  emptyCopy: { marginTop: 7, color: theme.muted, fontSize: 12, lineHeight: 20, textAlign: "center" },
  inlineError: { gap: 7, marginBottom: 12, padding: 11, borderRadius: 8, backgroundColor: theme.errorSoft },
  inlineNotice: { marginBottom: 12, padding: 11, borderRadius: 8, backgroundColor: theme.greenSoft },
  pendingBox: { gap: 8, marginBottom: 12, padding: 11, borderRadius: 8, backgroundColor: theme.riskSoft },
  pendingTitle: { color: theme.risk, fontSize: 12, fontWeight: "700" },
  pendingError: { color: theme.error, fontSize: 11, lineHeight: 18 },
  scopeDivider: { flexDirection: "row", alignItems: "center", gap: 8, marginVertical: 14 },
  scopeLine: { flex: 1, height: 1, backgroundColor: theme.border },
  scopeEvent: { color: theme.muted, fontSize: 10 },
  userMessage: { alignItems: "flex-end", marginBottom: 14 },
  pendingMessage: { alignItems: "flex-end", marginBottom: 14, opacity: 0.72 },
  pendingContext: { marginBottom: 4, color: theme.muted, fontSize: 10, fontWeight: "600" },
  pendingBubble: { backgroundColor: theme.green },
  contextTag: { marginBottom: 4, color: theme.green, fontSize: 10, fontWeight: "600" },
  userBubble: {
    maxWidth: "86%",
    paddingHorizontal: 13,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: theme.green,
  },
  userText: { color: "#FFFFFF", fontSize: 14, lineHeight: 22 },
  assistantMessage: { marginBottom: 3 },
  agentLabel: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 7 },
  agentDot: {
    width: 24,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
    backgroundColor: theme.aiSoft,
  },
  agentDotText: { color: theme.ai, fontSize: 11, fontWeight: "800" },
  agentLabelText: { color: theme.ink, fontSize: 12, fontWeight: "700" },
  legacyAnswer: {
    marginBottom: 12,
    padding: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  pressed: { opacity: 0.82 },
});
