import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  LayoutAnimation,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Platform,
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
import { CitationSheet } from "@/src/knowledge-agent/components/CitationSheet";
import { Composer } from "@/src/knowledge-agent/components/Composer";
import {
  DraftCard,
  DraftFailedCard,
  DraftProcessCard,
  DraftReceiptCard,
} from "@/src/knowledge-agent/components/DraftCard";
import { DraftConfirmSheet } from "@/src/knowledge-agent/components/DraftConfirmSheet";
import { DraftEditSheet } from "@/src/knowledge-agent/components/DraftEditSheet";
import { HistorySheet } from "@/src/knowledge-agent/components/HistorySheet";
import { ModeSheet } from "@/src/knowledge-agent/components/ModeSheet";
import { ProcessCard } from "@/src/knowledge-agent/components/ProcessCard";
import { ScopeSheet } from "@/src/knowledge-agent/components/ScopeSheet";
import {
  TargetProjectSheet,
  type DraftTargetOption,
} from "@/src/knowledge-agent/components/TargetProjectSheet";
import { useConversationController } from "@/src/knowledge-agent/hooks/useConversationController";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import { draftActionEligibility } from "@/src/knowledge-agent/adapters/answer";
import { scopeLabel } from "@/src/knowledge-agent/adapters/scope";
import { toUserErrorMessage } from "@/src/knowledge-agent/errors";
import type {
  KnowledgeCandidateDraft,
  KnowledgeMessage,
  KnowledgeRun,
  KnowledgeRunCitation,
  KnowledgeScopeChangeRequest,
} from "@/src/knowledge-agent/types";
import { isRunActive } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const SUGGESTIONS = [
  "帮我看看卫生间防水有哪些关键知识，有没有互相冲突的地方？",
  "现有知识里有哪些适用条件或缺口？",
];

export function ConversationScreen() {
  const { token } = useAuth();
  const controller = useConversationController(token);
  const insets = useSafeAreaInsets();
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const previousKeyboardHeightRef = useRef(0);
  // Android 键盘收起/弹出动画与 padding 瞬移不同步会导致输入框闪烁；
  // 高度变化时用 LayoutAnimation 平滑过渡，让 composer 跟随键盘动画。
  useEffect(() => {
    if (
      Platform.OS === "android" &&
      previousKeyboardHeightRef.current !== keyboardHeight
    ) {
      LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    }
    previousKeyboardHeightRef.current = keyboardHeight;
  }, [keyboardHeight]);
  const [text, setText] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [modeOpen, setModeOpen] = useState(false);
  const [citation, setCitation] = useState<KnowledgeRunCitation | null>(null);
  const [targetProject, setTargetProject] = useState<{
    sourceRunId: number;
    options: DraftTargetOption[];
  } | null>(null);
  const [editDraftId, setEditDraftId] = useState<number | null>(null);
  const [confirmDraftId, setConfirmDraftId] = useState<number | null>(null);
  const scrollRef = useRef<ScrollView>(null);

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => getProjects(token as string),
    // 项目仅供范围 Sheet 使用，延迟读取能避免对话首屏多一次无关请求与状态更新。
    enabled: Boolean(token && scopeOpen),
  });

  const submitting =
    controller.pending !== null &&
    (controller.pending.phase === "creating_conversation" ||
      controller.pending.phase === "submitting");

  const handleSend = useCallback(() => {
    // 先滚到底让 pending 气泡可见，提交成功后再对齐服务端消息
    scrollRef.current?.scrollToEnd({ animated: true });
    void controller.submit(text).then((submitted) => {
      // 只有确定成功才清空输入与滚动；失败时保留文本便于就地修改重试
      if (submitted) {
        setText("");
        scrollRef.current?.scrollToEnd({ animated: true });
      }
    });
  }, [controller, text]);

  const handleSuggestion = useCallback((suggestion: string) => {
    setText(suggestion);
  }, []);

  const handleScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      if (event.nativeEvent.contentOffset.y < 40) {
        void controller.loadOlderMessages();
      }
    },
    [controller],
  );

  const handleScopeChange = useCallback(
    (scope: KnowledgeScopeChangeRequest) => {
      setScopeOpen(false);
      void controller.changeScope(scope);
    },
    [controller],
  );

  const handleOrganize = useCallback(
    (run: KnowledgeRun) => {
      const eligibility = draftActionEligibility(run);
      if (!eligibility.eligible || eligibility.sourceRunId === null) return;
      if (eligibility.fixedProjectId !== null) {
        void controller.submitDraftAction(
          eligibility.sourceRunId,
          eligibility.fixedProjectId,
        );
        return;
      }
      if (eligibility.projectOptions.length === 1) {
        void controller.submitDraftAction(
          eligibility.sourceRunId,
          eligibility.projectOptions[0].id,
        );
        return;
      }
      setTargetProject({
        sourceRunId: eligibility.sourceRunId,
        options: eligibility.projectOptions,
      });
    },
    [controller],
  );

  const handleTargetSelect = useCallback(
    (sourceRunId: number, projectId: number) => {
      setTargetProject(null);
      void controller.submitDraftAction(sourceRunId, projectId);
    },
    [controller],
  );

  const editingDraft =
    editDraftId !== null ? controller.draftsById.get(editDraftId) ?? null : null;
  const confirmingDraft =
    confirmDraftId !== null
      ? controller.draftsById.get(confirmDraftId) ?? null
      : null;
  const editSaving = controller.draftEditBusy;
  const editError = controller.draftEditError;
  const confirmSaving = controller.confirmingDraftId !== null;
  const confirmError = controller.draftConfirmError;

  const threadHasMessages = controller.thread.items.length > 0;
  const draftIntroVisible =
    controller.isDraft && !threadHasMessages && !controller.initialLoading;

  const headerScopeLabel =
    controller.currentScope.scopeType === "project"
      ? controller.currentScope.projectName ?? "项目"
      : "全部知识";

  return (
    <SafeAreaView edges={["top"]} style={styles.page}>
      <View style={styles.page}>
        <View style={styles.header}>
          <View style={styles.brandMark}>
            <Text style={styles.brandText}>G</Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`修改当前知识范围，当前为${headerScopeLabel}`}
            onPress={() => setScopeOpen(true)}
            style={styles.scopeButton}
          >
            <Text numberOfLines={1} style={styles.scopeText}>
              {headerScopeLabel}
            </Text>
            <AgentIcon name="down" size={15} color={theme.muted} />
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="查看对话历史"
            onPress={() => setHistoryOpen(true)}
            style={styles.headerIcon}
          >
            <AgentIcon name="history" size={22} color={theme.muted} />
          </Pressable>
        </View>

        <ScrollView
          ref={scrollRef}
          style={styles.thread}
          contentContainerStyle={styles.threadContent}
          onScroll={handleScroll}
          scrollEventThrottle={100}
          keyboardShouldPersistTaps="handled"
          accessibilityLabel="知识 Agent 对话"
        >
          {controller.initialLoading && (
            <View style={styles.centerState}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.centerStateText}>正在恢复对话…</Text>
            </View>
          )}
          {controller.conversationsError !== null && (
            <View style={styles.inlineError}>
              <Text style={styles.inlineErrorTitle}>对话列表加载失败</Text>
              <Text style={styles.inlineErrorCopy}>{controller.conversationsError}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重试加载对话列表"
                onPress={controller.retryConversations}
                style={styles.retryButton}
              >
                <AgentIcon name="retry" size={16} color={theme.green} />
                <Text style={styles.retryText}>重试</Text>
              </Pressable>
            </View>
          )}
          {draftIntroVisible && (
            <View style={styles.intro}>
              <View style={styles.introMark}>
                <AgentIcon name="message" size={20} color={theme.green} />
              </View>
              <Text style={styles.introTitle}>和你的知识一起想</Text>
              <Text style={styles.introCopy}>
                当前只读取「{headerScopeLabel}」的正式知识。回答会展示可核验的来源，不会直接修改知识。
              </Text>
              <View style={styles.suggestions}>
                {SUGGESTIONS.map((suggestion) => (
                  <Pressable
                    key={suggestion}
                    accessibilityRole="button"
                    accessibilityLabel={`填入建议问题：${suggestion}`}
                    onPress={() => handleSuggestion(suggestion)}
                    style={({ pressed }) => [
                      styles.suggestion,
                      pressed && styles.pressed,
                    ]}
                  >
                    <View style={styles.suggestionIcon}>
                      <AgentIcon name="search" size={16} color={theme.green} />
                    </View>
                    <Text style={styles.suggestionText}>{suggestion}</Text>
                    <AgentIcon name="chevron" size={16} color={theme.muted} />
                  </Pressable>
                ))}
              </View>
            </View>
          )}
          {controller.messagesError !== null && threadHasMessages === false && (
            <View style={styles.inlineError}>
              <Text style={styles.inlineErrorTitle}>消息加载失败</Text>
              <Text style={styles.inlineErrorCopy}>{controller.messagesError}</Text>
            </View>
          )}
          {controller.loadingOlder && (
            <View style={styles.centerState}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.centerStateText}>正在加载更早消息…</Text>
            </View>
          )}
          {controller.olderError !== null && (
            <View style={styles.inlineError}>
              <Text style={styles.inlineErrorCopy}>{controller.olderError}</Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="重试加载更早消息"
                onPress={() => void controller.loadOlderMessages()}
                style={styles.retryButton}
              >
                <Text style={styles.retryText}>重试</Text>
              </Pressable>
            </View>
          )}
          {threadHasMessages &&
            controller.thread.items.map((message) => (
              <ThreadMessage
                key={message.id}
                message={message}
                run={controller.thread.runsById.get(message.runId ?? -1) ?? null}
                cancelling={controller.cancelling}
                pollingError={controller.runPollingError}
                cancelError={controller.cancelError}
                onCancelRun={controller.requestCancelRun}
                onRetryPolling={controller.retryRunPolling}
                onRetryRun={(runId) => void controller.retryRun(runId)}
                onCitationPress={setCitation}
                draft={controller.draftByRunId(message.runId ?? -1)}
                confirmingDraftId={controller.confirmingDraftId}
                onEditDraft={(draftId) => {
                  controller.clearDraftEditError();
                  setEditDraftId(draftId);
                }}
                onConfirmDraft={setConfirmDraftId}
                onCancelDraft={(draftId) => void controller.cancelDraft(draftId)}
                onRetryDraft={(sourceRunId, targetProjectId) =>
                  void controller.submitDraftAction(sourceRunId, targetProjectId)
                }
                onOrganize={handleOrganize}
              />
            ))}
          {controller.pending !== null && (
            <View>
              <View style={styles.pendingBubble}>
                <Text style={styles.pendingText}>{controller.pending.text}</Text>
              </View>
              <Text style={styles.pendingMeta}>
                {controller.pending.phase === "creating_conversation"
                  ? "正在创建对话并发送…"
                  : "发送中…"}
              </Text>
            </View>
          )}
          {controller.submitError !== null && (
            <View style={styles.inlineError}>
              <Text style={styles.inlineErrorTitle}>发送未完成</Text>
              <Text style={styles.inlineErrorCopy}>{controller.submitError}</Text>
              {controller.pending !== null && submitting && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="重试发送"
                  onPress={() => void controller.retrySubmit()}
                  style={styles.retryButton}
                >
                  <AgentIcon name="retry" size={16} color={theme.green} />
                  <Text style={styles.retryText}>重试发送</Text>
                </Pressable>
              )}
            </View>
          )}
          {controller.draftActionError !== null && (
            <View style={styles.inlineError}>
              <Text style={styles.inlineErrorTitle}>整理未完成</Text>
              <Text style={styles.inlineErrorCopy}>{controller.draftActionError}</Text>
              {controller.draftActionPending && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="重试整理"
                  onPress={() => void controller.retryDraftAction()}
                  style={styles.retryButton}
                >
                  <AgentIcon name="retry" size={16} color={theme.green} />
                  <Text style={styles.retryText}>重试整理</Text>
                </Pressable>
              )}
            </View>
          )}
        </ScrollView>

        <View style={{ paddingBottom: keyboardHeight }}>
          <Composer
            value={text}
            onChangeText={setText}
            onSend={handleSend}
            modes={controller.modes}
            onOpenModes={() => setModeOpen(true)}
            onRemoveContextOverride={() => controller.setContextMode("auto")}
            onRemoveAnswerOverride={() => controller.setAnswerMode("auto")}
            submitting={submitting}
            disabled={
              controller.initialLoading ||
              (controller.conversationsError !== null &&
                !controller.userInitiatedDraft)
            }
          />
        </View>
      </View>

      <HistorySheet
        visible={historyOpen}
        conversations={controller.conversations}
        activeConversationId={
          controller.isDraft ? null : controller.activeConversation?.id ?? null
        }
        loading={controller.initialLoading}
        error={controller.conversationsError}
        onSelect={(id) => {
          controller.switchToConversation(id);
          setHistoryOpen(false);
        }}
        onNew={() => {
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
        projectsError={
          projectsQuery.isError
            ? toUserErrorMessage(projectsQuery.error)
            : null
        }
        disabled={controller.activeRun !== null}
        disabledNote={
          controller.activeRun !== null
            ? "正在回答中，完成或取消当前回答后再切换范围。"
            : null
        }
        onChange={handleScopeChange}
        onClose={() => setScopeOpen(false)}
      />
      <ModeSheet
        visible={modeOpen}
        modes={controller.modes}
        onChange={(modes) => controller.setModes(modes)}
        onClose={() => setModeOpen(false)}
      />
      <CitationSheet citation={citation} onClose={() => setCitation(null)} />
      <TargetProjectSheet
        visible={targetProject !== null}
        options={targetProject?.options ?? []}
        sourceRunId={targetProject?.sourceRunId ?? null}
        submitting={controller.draftActionPending}
        error={controller.draftActionError}
        onSelect={handleTargetSelect}
        onClose={() => setTargetProject(null)}
      />
      <DraftEditSheet
        visible={editingDraft !== null}
        draft={editingDraft}
        saving={editSaving}
        error={editError}
        onSave={(title, content, mainType) => {
          if (editingDraft === null) return;
          void controller.editDraft(editingDraft.id, {
            title,
            content,
            mainType,
          }).then((saved) => {
            if (saved) setEditDraftId(null);
          });
        }}
        onClose={() => setEditDraftId(null)}
      />
      <DraftConfirmSheet
        visible={confirmingDraft !== null}
        draft={confirmingDraft}
        confirming={confirmSaving}
        error={confirmError}
        onConfirm={() => {
          if (confirmingDraft === null) return;
          void controller.confirmDraft(confirmingDraft.id).then((confirmed) => {
            if (confirmed) setConfirmDraftId(null);
          });
        }}
        onClose={() => setConfirmDraftId(null)}
      />
    </SafeAreaView>
  );
}

function ThreadMessage({
  message,
  run,
  cancelling,
  pollingError,
  cancelError,
  onCancelRun,
  onRetryPolling,
  onRetryRun,
  onCitationPress,
  draft,
  confirmingDraftId,
  onEditDraft,
  onConfirmDraft,
  onCancelDraft,
  onRetryDraft,
  onOrganize,
}: {
  message: KnowledgeMessage;
  run: KnowledgeRun | null;
  cancelling: boolean;
  pollingError: string | null;
  cancelError: string | null;
  onCancelRun: () => void;
  onRetryPolling: () => void;
  onRetryRun: (runId: number) => void;
  onCitationPress: (citation: KnowledgeRunCitation) => void;
  draft: KnowledgeCandidateDraft | null;
  confirmingDraftId: number | null;
  onEditDraft: (draftId: number) => void;
  onConfirmDraft: (draftId: number) => void;
  onCancelDraft: (draftId: number) => void;
  onRetryDraft: (sourceRunId: number, targetProjectId: number | null) => void;
  onOrganize: (run: KnowledgeRun) => void;
}) {
  if (message.messageType === "scope_change") {
    return (
      <View style={styles.scopeDivider}>
        <View style={styles.scopeDividerLine} />
        <Text style={styles.scopeDividerText}>{message.content}</Text>
        <View style={styles.scopeDividerLine} />
      </View>
    );
  }
  if (message.role === "user") {
    return (
      <View style={styles.userMessage}>
        <View style={styles.userBubble}>
          <Text style={styles.userBubbleText}>{message.content}</Text>
        </View>
      </View>
    );
  }
  const runScope = run
    ? scopeLabel(run.scopeType, run.projectName)
    : message.projectName ?? "全部知识";
  if (run?.runKind === "draft_candidate") {
    if (isRunActive(run.status) || draft?.status === "generating") {
      return (
        <View>
          <View style={styles.agentLabel}>
            <View style={styles.agentDot}>
              <Text style={styles.agentDotText}>G</Text>
            </View>
            <Text style={styles.agentLabelText}>知识 Agent</Text>
          </View>
          <DraftProcessCard
            run={run}
            cancelling={cancelling}
            onCancel={onCancelRun}
          />
        </View>
      );
    }
    if (draft === null) {
      return (
        <View>
          <View style={styles.agentLabel}>
            <View style={styles.agentDot}>
              <Text style={styles.agentDotText}>G</Text>
            </View>
            <Text style={styles.agentLabelText}>知识 Agent</Text>
          </View>
          {message.content.trim() !== "" && (
            <View style={styles.legacyAnswer}>
              <Text style={styles.legacyAnswerText}>{message.content}</Text>
            </View>
          )}
        </View>
      );
    }
    if (draft.status === "confirmed") {
      return (
        <View>
          <View style={styles.agentLabel}>
            <View style={styles.agentDot}>
              <Text style={styles.agentDotText}>G</Text>
            </View>
            <Text style={styles.agentLabelText}>知识 Agent</Text>
          </View>
          <DraftReceiptCard draft={draft} />
        </View>
      );
    }
    if (draft.status === "draft" || draft.status === "confirming") {
      return (
        <View>
          <View style={styles.agentLabel}>
            <View style={styles.agentDot}>
              <Text style={styles.agentDotText}>G</Text>
            </View>
            <Text style={styles.agentLabelText}>知识 Agent</Text>
          </View>
          <DraftCard
            draft={draft}
            confirming={confirmingDraftId === draft.id}
            onEdit={() => onEditDraft(draft.id)}
            onConfirm={() => onConfirmDraft(draft.id)}
            onCancel={() => onCancelDraft(draft.id)}
          />
        </View>
      );
    }
    if (draft.status === "failed" || draft.status === "cancelled") {
      return (
        <View>
          <View style={styles.agentLabel}>
            <View style={styles.agentDot}>
              <Text style={styles.agentDotText}>G</Text>
            </View>
            <Text style={styles.agentLabelText}>知识 Agent</Text>
          </View>
          <DraftFailedCard
            draft={draft}
            onRetry={() => {
              if (draft.sourceRunId !== null) {
                onRetryDraft(draft.sourceRunId, draft.targetProjectId);
              }
            }}
          />
        </View>
      );
    }
  }
  return (
    <View>
      <View style={styles.agentLabel}>
        <View style={styles.agentDot}>
          <Text style={styles.agentDotText}>G</Text>
        </View>
        <Text style={styles.agentLabelText}>知识 Agent</Text>
      </View>
      {run === null ? (
        message.content.trim() !== "" && (
          <View style={styles.legacyAnswer}>
            <Text style={styles.legacyAnswerText}>{message.content}</Text>
          </View>
        )
      ) : isRunActive(run.status) ? (
        <ProcessCard
          run={run}
          scopeLabel={runScope}
          cancelling={cancelling}
          pollingError={pollingError}
          cancelError={cancelError}
          onCancel={onCancelRun}
          onRetryPolling={onRetryPolling}
        />
      ) : (
        <AnswerCard
          run={run}
          scopeLabel={runScope}
          onCitationPress={onCitationPress}
          onOrganize={onOrganize}
          onRetry={() => {
            onRetryRun(run.id);
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: theme.bg },
  header: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
    backgroundColor: theme.surface,
  },
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
    alignSelf: "center",
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    maxWidth: 220,
    paddingHorizontal: 5,
    borderRadius: 8,
  },
  scopeText: {
    fontSize: 15,
    lineHeight: 21,
    fontWeight: "700",
    color: theme.ink,
    maxWidth: 180,
  },
  headerIcon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
  },
  thread: { flex: 1 },
  // Composer 是正常布局兄弟节点，键盘高度由 composer 下方 padding 垫起；
  // 这里只保留阅读呼吸空间，不重复预留固定 Composer 高度。
  threadContent: { paddingHorizontal: 16, paddingTop: 18, paddingBottom: 18 },
  intro: { paddingTop: 44 },
  introMark: {
    width: 38,
    height: 38,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 9,
    backgroundColor: theme.greenSoft,
    marginBottom: 20,
  },
  introTitle: {
    fontSize: 23,
    lineHeight: 31,
    fontWeight: "700",
    letterSpacing: -0.5,
    color: theme.ink,
  },
  introCopy: {
    marginTop: 8,
    maxWidth: 315,
    color: theme.muted,
    fontSize: 13,
    lineHeight: 21,
  },
  suggestions: { gap: 9, marginTop: 28 },
  suggestion: {
    minHeight: 52,
    flexDirection: "row",
    alignItems: "center",
    gap: 11,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
    shadowColor: "#14281E",
    shadowOpacity: 0.05,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  suggestionIcon: {
    width: 30,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 7,
    backgroundColor: theme.greenSoft,
  },
  suggestionText: {
    flex: 1,
    minWidth: 0,
    fontSize: 13,
    fontWeight: "600",
    color: theme.ink,
  },
  pressed: { opacity: 0.85 },
  userMessage: { alignItems: "flex-end", marginBottom: 14 },
  userBubble: {
    maxWidth: "84%",
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderTopLeftRadius: 14,
    borderTopRightRadius: 14,
    borderBottomLeftRadius: 14,
    borderBottomRightRadius: 4,
    backgroundColor: theme.green,
  },
  userBubbleText: { color: "#FFFFFF", fontSize: 14, lineHeight: 21 },
  pendingBubble: {
    alignSelf: "flex-end",
    maxWidth: "84%",
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderTopLeftRadius: 14,
    borderTopRightRadius: 14,
    borderBottomLeftRadius: 14,
    borderBottomRightRadius: 4,
    backgroundColor: theme.green,
    opacity: 0.72,
  },
  pendingText: { color: "#FFFFFF", fontSize: 14, lineHeight: 21 },
  pendingMeta: {
    alignSelf: "flex-end",
    marginTop: 5,
    marginBottom: 14,
    color: theme.muted,
    fontSize: 10,
  },
  agentLabel: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 20,
    marginBottom: 8,
  },
  agentDot: {
    width: 18,
    height: 18,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 5,
    backgroundColor: theme.greenSoft,
  },
  agentDotText: { color: theme.green, fontSize: 10, fontWeight: "700" },
  agentLabelText: { color: theme.muted, fontSize: 11, fontWeight: "600" },
  legacyAnswer: {
    marginBottom: 12,
    padding: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  legacyAnswerText: { fontSize: 14, lineHeight: 23, color: theme.ink },
  scopeDivider: {
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    marginVertical: 13,
  },
  scopeDividerLine: { flex: 1, height: 1, backgroundColor: theme.border },
  scopeDividerText: {
    flexShrink: 1,
    color: theme.muted,
    fontSize: 10,
  },
  centerState: {
    alignItems: "center",
    paddingVertical: 36,
    gap: 10,
  },
  centerStateText: { color: theme.muted, fontSize: 12 },
  inlineError: {
    marginBottom: 12,
    padding: 13,
    borderWidth: 1,
    borderColor: "#EFCACA",
    borderRadius: 10,
    backgroundColor: theme.errorSoft,
  },
  inlineErrorTitle: { color: theme.error, fontSize: 13, fontWeight: "700" },
  inlineErrorCopy: { marginTop: 4, color: "#7C2E2E", fontSize: 12, lineHeight: 19 },
  retryButton: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: 8,
  },
  retryText: { color: theme.green, fontSize: 13, fontWeight: "600" },
});
