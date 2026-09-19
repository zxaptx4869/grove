import { useMemo, useRef, useState } from "react";
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
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import { ModeSheet } from "@/src/knowledge-agent/components/ModeSheet";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { ScopeSheet } from "@/src/knowledge-agent/components/ScopeSheet";
import { toUserErrorMessage } from "@/src/knowledge-agent/errors";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import type {
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
  const [text, setText] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  const projectsQuery = useQuery({
    queryKey: ["projects", "mobile-scope"],
    queryFn: () => getProjects(token as string),
    enabled: Boolean(token),
  });

  const runByAssistantMessage = useMemo(() => {
    const map = new Map<number, KnowledgeRun>();
    for (const run of controller.thread.runsById.values()) {
      if (run.assistantMessageId !== null) map.set(run.assistantMessageId, run);
    }
    return map;
  }, [controller.thread.runsById]);

  const handleSend = async () => {
    const value = text.trim();
    if (!value) return;
    const sent = await controller.submit(value);
    if (sent) setText("");
  };

  const handleScopeChange = async (scope: KnowledgeScopeChangeRequest) => {
    await controller.changeScope(scope);
    setScopeOpen(false);
  };

  const handleScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    scrollYRef.current = contentOffset.y;
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
    if (stickToBottomRef.current) scrollRef.current?.scrollToEnd({ animated: true });
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
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="打开对话历史"
            onPress={() => setHistoryOpen(true)}
            style={({ pressed }) => [styles.iconButton, pressed && styles.pressed]}
          >
            <AgentIcon name="history" size={21} color={theme.ink} />
          </Pressable>
          <View style={styles.headerMain}>
            <Text style={styles.title}>知识 Agent</Text>
            <Text style={styles.subtitle} numberOfLines={1}>
              {controller.isDraft ? "新对话" : controller.activeConversation?.title ?? "正在恢复"}
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`当前知识范围：${controller.scopeLabel}`}
            onPress={() => setScopeOpen(true)}
            style={({ pressed }) => [styles.scopeButton, pressed && styles.pressed]}
          >
            <AgentIcon
              name={controller.currentScope.scopeType === "project" ? "folder" : "book"}
              size={15}
              color={theme.green}
            />
            <Text style={styles.scopeButtonText} numberOfLines={1}>
              {controller.scopeLabel}
            </Text>
            <AgentIcon name="down" size={14} color={theme.green} />
          </Pressable>
        </View>

        <ScrollView
          ref={scrollRef}
          style={styles.thread}
          contentContainerStyle={styles.threadContent}
          keyboardShouldPersistTaps="handled"
          scrollEventThrottle={16}
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
            />
          ))}

          {controller.pending ? (
            <View style={styles.pendingBox}>
              <Text style={styles.pendingTitle}>消息提交结果尚未确认</Text>
              <Text style={styles.stateCopy}>{controller.pending.text}</Text>
              {controller.submitError ? (
                <Text style={styles.pendingError}>{controller.submitError}</Text>
              ) : null}
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="使用同一标识重试提交"
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
        </ScrollView>

        <View style={{ paddingBottom: keyboardHeight }}>
          <Composer
            value={text}
            onChangeText={setText}
            onSend={() => void handleSend()}
            modes={controller.modes}
            onOpenModes={() => setModeOpen(true)}
            onRemoveContextOverride={() => controller.setContextMode("auto")}
            submitting={controller.pending !== null}
            disabled={
              controller.initialLoading ||
              controller.activeRun !== null ||
              (controller.conversationsError !== null && !controller.userInitiatedDraft)
            }
          />
        </View>
      </View>

      <HistorySheet
        visible={historyOpen}
        conversations={controller.conversations}
        activeConversationId={controller.isDraft ? null : controller.activeConversation?.id ?? null}
        loading={controller.initialLoading}
        error={controller.conversationsError}
        onSelect={(id) => {
          stickToBottomRef.current = true;
          controller.switchToConversation(id);
          setHistoryOpen(false);
        }}
        onNew={() => {
          stickToBottomRef.current = true;
          controller.startNewConversation();
          setHistoryOpen(false);
        }}
        onClose={() => setHistoryOpen(false)}
      />
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
    </SafeAreaView>
  );
}

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
            <Text style={styles.legacyText}>{message.content}</Text>
          </View>
        ) : null
      ) : isRunActive(run.status) ? (
        <ProcessCard
          run={run}
          scopeLabel={runScope}
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
    gap: 8,
    paddingHorizontal: 10,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
  iconButton: { width: 42, height: 42, alignItems: "center", justifyContent: "center" },
  headerMain: { flex: 1, minWidth: 0 },
  title: { color: theme.ink, fontSize: 15, fontWeight: "700" },
  subtitle: { marginTop: 2, color: theme.muted, fontSize: 10 },
  scopeButton: {
    maxWidth: 132,
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 9,
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  scopeButtonText: { flexShrink: 1, color: theme.green, fontSize: 11, fontWeight: "600" },
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
  pendingBox: { gap: 8, marginBottom: 12, padding: 11, borderRadius: 8, backgroundColor: theme.riskSoft },
  pendingTitle: { color: theme.risk, fontSize: 12, fontWeight: "700" },
  pendingError: { color: theme.error, fontSize: 11, lineHeight: 18 },
  scopeDivider: { flexDirection: "row", alignItems: "center", gap: 8, marginVertical: 14 },
  scopeLine: { flex: 1, height: 1, backgroundColor: theme.border },
  scopeEvent: { color: theme.muted, fontSize: 10 },
  userMessage: { alignItems: "flex-end", marginBottom: 14 },
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
  legacyText: { color: theme.ink, fontSize: 14, lineHeight: 23 },
  pressed: { opacity: 0.82 },
});
