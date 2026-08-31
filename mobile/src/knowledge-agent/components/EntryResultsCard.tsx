import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import {
  Badge,
  Card,
  CardBody,
  Eyebrow,
} from "@/src/knowledge-agent/components/ui";
import {
  completenessCopy,
  resultStatusCopy,
} from "@/src/knowledge-agent/adapters/entryResults";
import type { EntryResultsState } from "@/src/knowledge-agent/hooks/useConversationController";
import type {
  KnowledgeEntryResultItem,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const TYPE_LABELS: Record<string, string> = {
  knowledge: "知识",
  method: "方法",
  parameter: "参数",
  reminder: "提醒",
};

function typeLabel(value: string | null): string {
  return value ? (TYPE_LABELS[value] ?? value) : "知识";
}

function updatedLabel(updatedAt: string | null): string {
  if (!updatedAt) return "—";
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return "—";
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function EntryResultRow({
  item,
  index,
  onPress,
}: {
  item: KnowledgeEntryResultItem;
  index: number;
  onPress: (item: KnowledgeEntryResultItem) => void;
}) {
  const path = [item.projectName, item.nodePath].filter(Boolean).join(" / ");
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`第 ${index + 1} 条，正式知识，${item.title}，${
        path || "归属未标注"
      }`}
      onPress={() => onPress(item)}
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <View style={styles.rowTop}>
        <Badge tone="confirmed">正式知识</Badge>
        {path !== "" && (
          <Text style={styles.rowPath} numberOfLines={1}>
            {path}
          </Text>
        )}
      </View>
      <Text style={styles.rowTitle} numberOfLines={2}>
        {item.title}
      </Text>
      {item.excerpt.trim() !== "" && (
        <Text style={styles.rowExcerpt} numberOfLines={2}>
          {item.excerpt}
        </Text>
      )}
      <View style={styles.rowMeta}>
        <Text style={styles.rowMetaText}>{typeLabel(item.mainType)}</Text>
        <Text style={styles.rowMetaDot}>·</Text>
        <Text style={styles.rowMetaText}>{item.sourceCount} 个来源</Text>
        <Text style={styles.rowMetaDot}>·</Text>
        <Text style={styles.rowMetaText}>更新于 {updatedLabel(item.updatedAt)}</Text>
      </View>
      {item.matchHint !== null && (
        <View style={styles.hintBox}>
          <AgentIcon name="search" size={13} color={theme.green} />
          <Text style={styles.hintText} numberOfLines={2}>
            {item.matchHint}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

export function EntryResultsCard({
  run,
  scopeLabel,
  state,
  onPrime,
  onLoadMore,
  onRetry,
  onOpenItem,
  onCorrectMode,
  onRefine,
}: {
  run: KnowledgeRun;
  scopeLabel: string;
  state: EntryResultsState;
  onPrime: () => void;
  onLoadMore: () => void;
  onRetry: () => void;
  onOpenItem: (item: KnowledgeEntryResultItem) => void;
  onCorrectMode: () => void;
  onRefine: () => void;
}) {
  const snapshot = run.entryResult;
  const total = snapshot?.returnedCount ?? state.items.length;
  const completeness = snapshot?.completeness ?? "unknown";
  const items = state.items;
  const isEmpty = items.length === 0 && !state.loadingMore;

  if (run.status === "cancelled") {
    return (
      <Card>
        <CardBody>
          <View style={styles.head}>
            <View style={styles.headMain}>
              <Eyebrow icon={<AgentIcon name="alert" size={14} color={theme.muted} />}>
                已取消
              </Eyebrow>
              <Text style={styles.title}>这次查找已取消</Text>
            </View>
            <Badge tone="neutral">已取消</Badge>
          </View>
          <Text style={styles.copy}>没有生成知识列表，可以重新提问。</Text>
          <View style={styles.actions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="重新提问"
              onPress={onRefine}
              style={({ pressed }) => [
                styles.correctButton,
                pressed && styles.pressed,
              ]}
            >
              <Text style={styles.correctText}>重新提问</Text>
            </Pressable>
          </View>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardBody>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="book" size={14} color={theme.confirmed} />}>
              结构化知识结果
            </Eyebrow>
            <Text style={styles.title}>找到 {total} 条相关知识</Text>
          </View>
          <Badge tone="confirmed">正式知识</Badge>
        </View>
        <View style={styles.scopeRow}>
          <AgentIcon name="folder" size={14} color={theme.muted} />
          <Text style={styles.scopeText}>检索范围：{scopeLabel}</Text>
        </View>
        <Text style={styles.completenessCopy}>{completenessCopy(completeness)}</Text>
        {snapshot?.status === "partial" && (
          <Text style={styles.partialCopy}>{resultStatusCopy(snapshot)}</Text>
        )}
        {snapshot?.warning !== null && snapshot?.warning !== undefined && (
          <Text style={styles.warningCopy}>{snapshot.warning}</Text>
        )}

        {isEmpty ? (
          <View style={styles.emptyBox}>
            <Text style={styles.emptyTitle}>没有找到匹配的正式知识</Text>
            <Text style={styles.emptyCopy}>
              当前范围内没有匹配的已确认知识，可修改问题或缩小条件再找。
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="修改问题"
              onPress={onRefine}
              style={({ pressed }) => [
                styles.refineButton,
                pressed && styles.pressed,
              ]}
            >
              <Text style={styles.refineText}>修改问题</Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.rows}>
            {items.map((item, index) => (
              <EntryResultRow
                key={item.entryId}
                item={item}
                index={index}
                onPress={onOpenItem}
              />
            ))}
          </View>
        )}

        {!isEmpty && (
          <View style={styles.footer}>
            <Text style={styles.loadedCopy}>
              已显示 {items.length} 条
              {snapshot && snapshot.items.length > items.length
                ? ` / 快照共 ${snapshot.items.length} 条`
                : ""}
            </Text>
            {state.error !== null && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>
                  加载更多失败：{state.error}。已显示的结果不会丢失。
                </Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="重试加载更多结果"
                  onPress={onRetry}
                  style={({ pressed }) => [
                    styles.retryButton,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={styles.retryText}>重试</Text>
                </Pressable>
              </View>
            )}
            {state.loadingMore ? (
              <View style={styles.loadingMore}>
                <ActivityIndicator color={theme.green} size="small" />
                <Text style={styles.loadingMoreText}>正在加载更多…</Text>
              </View>
            ) : state.hasMore ? (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="加载更多结果"
                onPress={onLoadMore}
                style={({ pressed }) => [
                  styles.loadMoreButton,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.loadMoreText}>加载更多</Text>
              </Pressable>
            ) : (
              (completeness === "limited" || completeness === "unknown") && (
                <Text style={styles.moreCopy}>
                  已显示本次快照全部结果，可缩小条件再找
                </Text>
              )
            )}
            <View style={styles.actions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="改为综合回答"
                onPress={onCorrectMode}
                style={({ pressed }) => [
                  styles.correctButton,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.correctText}>改为综合回答</Text>
              </Pressable>
            </View>
          </View>
        )}
      </CardBody>
    </Card>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10,
  },
  headMain: { minWidth: 0, flex: 1 },
  title: {
    marginTop: 4,
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: theme.ink,
  },
  scopeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  scopeText: { color: theme.muted, fontSize: 10, lineHeight: 16 },
  completenessCopy: {
    marginTop: 8,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  partialCopy: {
    marginTop: 4,
    color: theme.risk,
    fontSize: 11,
    lineHeight: 18,
  },
  warningCopy: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  rows: {
    marginTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  row: {
    paddingVertical: 12,
    paddingHorizontal: 2,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  rowPressed: { opacity: 0.82, backgroundColor: theme.soft },
  rowTop: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  rowPath: {
    flex: 1,
    minWidth: 0,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  rowTitle: {
    marginTop: 7,
    fontSize: 14,
    lineHeight: 21,
    fontWeight: "700",
    color: theme.ink,
  },
  rowExcerpt: {
    marginTop: 4,
    fontSize: 11,
    lineHeight: 18,
    color: theme.muted,
  },
  rowMeta: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 7,
  },
  rowMetaText: { color: theme.muted, fontSize: 10, lineHeight: 16 },
  rowMetaDot: { color: theme.faint, fontSize: 10 },
  hintBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 5,
    marginTop: 8,
    padding: 8,
    borderRadius: 6,
    backgroundColor: theme.greenSoft,
  },
  hintText: {
    flex: 1,
    color: theme.green,
    fontSize: 11,
    lineHeight: 17,
  },
  emptyBox: {
    marginTop: 12,
    padding: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.bg,
  },
  emptyTitle: { fontSize: 13, fontWeight: "700", color: theme.ink },
  emptyCopy: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  refineButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  refineText: { fontSize: 13, fontWeight: "600", color: theme.ink },
  footer: { marginTop: 12 },
  loadedCopy: { color: theme.muted, fontSize: 10, lineHeight: 16 },
  errorBox: {
    marginTop: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: "#EFCACA",
    borderRadius: 7,
    backgroundColor: theme.errorSoft,
  },
  errorText: { color: "#7C2E2E", fontSize: 11, lineHeight: 18 },
  retryButton: {
    minHeight: 40,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 6,
  },
  retryText: { color: theme.green, fontSize: 12, fontWeight: "600" },
  loadingMore: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    minHeight: 44,
    marginTop: 8,
  },
  loadingMoreText: { color: theme.muted, fontSize: 12 },
  loadMoreButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 8,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  loadMoreText: { color: theme.green, fontSize: 13, fontWeight: "600" },
  moreCopy: {
    marginTop: 10,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  actions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 12,
    flexWrap: "wrap",
  },
  correctButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    flex: 1,
    borderWidth: 1,
    borderColor: "#DACCDE",
    borderRadius: 8,
    backgroundColor: theme.aiSoft,
  },
  correctText: { color: theme.ai, fontSize: 13, fontWeight: "600" },
  pressed: { opacity: 0.85 },
  copy: { marginTop: 10, fontSize: 14, lineHeight: 23, color: theme.ink },
});
