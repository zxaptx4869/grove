import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { Badge, Sheet } from "@/src/knowledge-agent/components/ui";
import type {
  KnowledgeConversation,
  RunStatus,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

function relativeTime(iso: string): string {
  const value = new Date(iso).getTime();
  if (Number.isNaN(value)) return "";
  const diffMinutes = Math.round((Date.now() - value) / 60000);
  if (diffMinutes < 1) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小时前`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays === 1) return "昨天";
  if (diffDays < 7) return `${diffDays} 天前`;
  return new Date(iso).toLocaleDateString();
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

export function HistorySheet({
  visible,
  conversations,
  activeConversationId,
  loading,
  error,
  onSelect,
  onNew,
  onClose,
}: {
  visible: boolean;
  conversations: KnowledgeConversation[] | undefined;
  activeConversationId: number | null;
  loading: boolean;
  error: string | null;
  onSelect: (conversationId: number) => void;
  onNew: () => void;
  onClose: () => void;
}) {
  return (
    <Sheet visible={visible} title="对话历史" onClose={onClose}>
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
      {loading && <Text style={styles.hint}>正在加载对话历史…</Text>}
      {error !== null && <Text style={styles.error}>对话历史加载失败：{error}</Text>}
      {!loading && error === null && conversations?.length === 0 && (
        <Text style={styles.hint}>还没有对话，发送第一条问题即可创建。</Text>
      )}
      {conversations?.map((conversation) => {
        const selected = conversation.id === activeConversationId;
        return (
          <Pressable
            key={conversation.id}
            accessibilityRole="button"
            accessibilityLabel={`切换到对话：${conversation.title}`}
            accessibilityState={{ selected }}
            onPress={() => onSelect(conversation.id)}
            style={({ pressed }) => [styles.row, pressed && styles.pressed]}
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
        );
      })}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  newRow: { marginBottom: 10 },
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
  row: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
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
  error: { color: theme.error, paddingVertical: 18, fontSize: 12 },
});
