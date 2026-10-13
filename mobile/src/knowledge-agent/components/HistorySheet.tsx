import { useContext, useState } from "react";
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaInsetsContext } from "react-native-safe-area-context";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import type { ConversationActionResult } from "@/src/knowledge-agent/hooks/useConversationController";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import { useReducedMotion } from "@/src/knowledge-agent/hooks/useReducedMotion";
import { AppButton, Badge, Sheet } from "@/src/knowledge-agent/components/ui";
import type {
  KnowledgeConversation,
  RunStatus,
} from "@/src/knowledge-agent/types";
import { parseServerTime } from "@/src/serverTime";
import { theme } from "@/src/theme";

const ZERO_INSETS = { top: 0, right: 0, bottom: 0, left: 0 };

function relativeTime(iso: string): string {
  // 解析统一走 @/src/serverTime：裸串按 UTC，刚结束的对话不会显示成「8 小时前」
  const value = parseServerTime(iso).getTime();
  if (Number.isNaN(value)) return "";
  const diffMinutes = Math.round((Date.now() - value) / 60000);
  if (diffMinutes < 1) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays === 1) return "昨天";
  if (diffDays < 7) return `${diffDays} 天前`;
  return parseServerTime(iso).toLocaleDateString();
}

const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  waiting: "等待中",
  processing: "进行中",
  completed: "已回答",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
};

function conversationStatus(conversation: KnowledgeConversation): string {
  const scopePrefix =
    conversation.scopeType === "project" ? "项目范围" : "Workspace 范围";
  if (conversation.recentRunId === null) {
    return `${scopePrefix} · 尚无回答`;
  }
  return `${scopePrefix} · ${RUN_STATUS_LABELS[conversation.recentRunStatus ?? "completed"]}`;
}

export interface HistoryAction {
  /** menu 为长按后的操作小窗；rename/delete 为对应的表单或确认面板。 */
  type: "menu" | "rename" | "delete";
  conversation: KnowledgeConversation;
}

/** 底部弹层里的表单区：重命名成功后只更新该行标题，列表保持挂载。 */
function ConversationActionPanel({
  action,
  onRename,
  onDelete,
  onClose,
}: {
  action: HistoryAction;
  onRename: (
    conversationId: number,
    title: string,
  ) => Promise<ConversationActionResult>;
  onDelete: (conversationId: number) => Promise<ConversationActionResult>;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(action.conversation.title);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submitRename = async () => {
    if (busy) return;
    const trimmed = title.trim();
    if (!trimmed) {
      setError("标题不能为空");
      return;
    }
    if (trimmed.length > 255) {
      setError("标题不能超过 255 个字符");
      return;
    }
    setError(null);
    setBusy(true);
    const result = await onRename(action.conversation.id, trimmed);
    setBusy(false);
    if (result.ok) {
      onClose();
      return;
    }
    setError(result.message ?? "重命名失败，请重试");
  };

  const submitDelete = async () => {
    if (busy) return;
    setError(null);
    setBusy(true);
    const result = await onDelete(action.conversation.id);
    setBusy(false);
    if (result.ok) {
      onClose();
      return;
    }
    setError(result.message ?? "删除失败，请重试");
  };

  return (
    <View style={styles.actionPanel}>
      {action.type === "rename" ? (
        <>
          <Text style={styles.actionCopy}>只修改列表里的对话名称，消息与问答记录保持不变。</Text>
          <TextInput
            testID="conversation-rename-input"
            accessibilityLabel="对话名称"
            value={title}
            onChangeText={setTitle}
            maxLength={255}
            autoFocus
            style={styles.actionInput}
          />
        </>
      ) : (
        <Text style={styles.actionCopy}>
          「{action.conversation.title}」将从列表移除，对话内容保留。
        </Text>
      )}
      {error !== null ? (
        <Text style={styles.actionError} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
      <View style={styles.actionButtons}>
        <AppButton label="取消" variant="ghost" onPress={onClose} />
        {action.type === "rename" ? (
          <AppButton
            label={busy ? "保存中…" : "保存"}
            variant="primary"
            disabled={busy}
            onPress={() => void submitRename()}
          />
        ) : (
          <AppButton
            label={busy ? "删除中…" : "确认删除"}
            variant="danger"
            disabled={busy}
            onPress={() => void submitDelete()}
          />
        )}
      </View>
    </View>
  );
}

export function HistorySheet({
  visible,
  conversations,
  activeConversationId,
  loading,
  error,
  action,
  onRetry,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onActionChange,
  onClose,
}: {
  visible: boolean;
  conversations: KnowledgeConversation[] | undefined;
  activeConversationId: number | null;
  loading: boolean;
  error: string | null;
  action: HistoryAction | null;
  onRetry: () => void;
  onSelect: (conversationId: number) => void;
  onNew: () => void;
  onRename: (
    conversationId: number,
    title: string,
  ) => Promise<ConversationActionResult>;
  onDelete: (conversationId: number) => Promise<ConversationActionResult>;
  onActionChange: (action: HistoryAction | null) => void;
  onClose: () => void;
}) {
  const insets = useContext(SafeAreaInsetsContext) ?? ZERO_INSETS;
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const reducedMotion = useReducedMotion();
  const popupTitle =
    action?.type === "rename"
      ? "重命名对话"
      : action?.type === "delete"
        ? "删除对话"
        : "对话操作";
  return (
    <Sheet visible={visible} title="对话历史" onClose={onClose} scrollable={false}>
      <View style={styles.body}>
        <View style={styles.newRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="新建对话"
            onPress={onNew}
            style={({ pressed }) => [styles.newButton, pressed && styles.pressed]}
          >
            <AgentIcon name="plus" size={16} color={theme.green} />
            <Text style={styles.newButtonText}>新建对话</Text>
          </Pressable>
        </View>
        <FlatList
          testID="conversation-history-list"
          data={conversations ?? []}
          keyExtractor={(conversation) => String(conversation.id)}
          initialNumToRender={12}
          maxToRenderPerBatch={12}
          windowSize={5}
          removeClippedSubviews
          keyboardShouldPersistTaps="handled"
          style={styles.list}
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={
            <View>
            {loading ? <Text style={styles.hint}>正在加载对话历史…</Text> : null}
            {error !== null ? (
              <View style={styles.errorBox} accessibilityRole="alert">
                <Text style={styles.error}>对话历史加载失败：{error}</Text>
                <AppButton
                  label="重试加载历史"
                  variant="ghost"
                  onPress={onRetry}
                  icon={<AgentIcon name="retry" size={15} color={theme.ink} />}
                />
              </View>
            ) : null}
            </View>
          }
          ListEmptyComponent={
            !loading && error === null ? (
              <Text style={styles.hint}>还没有对话，发送第一条问题即可创建。</Text>
            ) : null
          }
          renderItem={({ item: conversation }) => {
          const selected = conversation.id === activeConversationId;
          return (
            <View style={styles.row}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`切换到对话：${conversation.title}`}
                accessibilityHint="长按可重命名或删除该对话"
                accessibilityState={{ selected }}
                accessibilityActions={[
                  { name: "rename", label: `重命名对话：${conversation.title}` },
                  { name: "delete", label: `删除对话：${conversation.title}` },
                ]}
                onAccessibilityAction={(event) => {
                  const name = event.nativeEvent.actionName;
                  if (name === "rename") {
                    onActionChange({ type: "rename", conversation });
                  } else if (name === "delete") {
                    onActionChange({ type: "delete", conversation });
                  }
                }}
                onPress={() => onSelect(conversation.id)}
                onLongPress={() => onActionChange({ type: "menu", conversation })}
                delayLongPress={300}
                style={({ pressed }) => [styles.rowSwitch, pressed && styles.pressed]}
              >
                <View style={styles.rowTop}>
                  <Badge tone={selected ? "confirmed" : "neutral"}>
                    {conversation.scopeType === "project"
                      ? conversation.projectName ?? "项目"
                      : "全部知识"}
                  </Badge>
                  <Text style={styles.time}>{relativeTime(conversation.lastActivityAt)}</Text>
                </View>
                <Text style={styles.rowTitle} numberOfLines={1}>
                  {conversation.title}
                </Text>
                <Text style={styles.rowStatus}>
                  {conversation.activeTopicLabel
                    ? `主题：${conversation.activeTopicLabel} · `
                    : ""}
                  {conversationStatus(conversation)}
                </Text>
              </Pressable>
            </View>
          );
          }}
        />
      </View>
      <Sheet
        visible={action !== null}
        title={popupTitle}
        onClose={() => onActionChange(null)}
        presentation="bottom"
        reduceMotion={reducedMotion}
        scrollable={false}
        bottomOffset={action?.type === "rename" ? keyboardHeight : 0}
      >
        {action !== null && action.type === "menu" ? (
          <View style={styles.actionPanel}>
            <Text style={styles.actionCopy} numberOfLines={2}>
              {action.conversation.title}
            </Text>
            <AppButton
              label="重命名"
              variant="ghost"
              icon={<AgentIcon name="edit" size={15} color={theme.green} />}
              onPress={() =>
                onActionChange({ type: "rename", conversation: action.conversation })
              }
            />
            <AppButton
              label="删除"
              variant="danger"
              onPress={() =>
                onActionChange({ type: "delete", conversation: action.conversation })
              }
            />
            <AppButton label="取消" variant="ghost" onPress={() => onActionChange(null)} />
          </View>
        ) : null}
        {action !== null && action.type !== "menu" ? (
          <ConversationActionPanel
            key={`${action.type}-${action.conversation.id}`}
            action={action}
            onRename={onRename}
            onDelete={onDelete}
            onClose={() => onActionChange(null)}
          />
        ) : null}
      </Sheet>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  body: { flexShrink: 1 },
  list: { flexGrow: 0 },
  listContent: { paddingHorizontal: 16, paddingBottom: 18 },
  newRow: { paddingHorizontal: 16, paddingTop: 8, paddingBottom: 10 },
  newButton: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: "#BAD5C5",
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  newButtonText: { color: theme.green, fontSize: 13, fontWeight: "700" },
  pressed: { opacity: 0.85 },
  actionPanel: {
    paddingHorizontal: 16,
    paddingTop: 4,
    paddingBottom: 12,
    gap: 8,
  },
  actionCopy: { color: theme.muted, fontSize: 12, lineHeight: 18 },
  actionInput: {
    minHeight: 44,
    paddingHorizontal: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
    color: theme.ink,
    fontSize: 14,
  },
  actionError: { color: theme.error, fontSize: 12, lineHeight: 18 },
  actionButtons: { flexDirection: "row", justifyContent: "flex-end", gap: 8 },
  row: {
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  rowSwitch: { paddingTop: 12, paddingBottom: 12 },
  rowTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  time: { color: theme.muted, fontSize: 10 },
  rowTitle: {
    marginTop: 7,
    fontSize: 14,
    lineHeight: 21,
    fontWeight: "700",
    color: theme.ink,
  },
  rowStatus: {
    marginTop: 3,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  hint: { color: theme.muted, paddingVertical: 18, fontSize: 12 },
  error: { color: theme.error, paddingVertical: 12, fontSize: 12 },
  errorBox: { marginBottom: 8 },
});
