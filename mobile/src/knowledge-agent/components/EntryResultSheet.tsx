import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/src/auth";
import { AppButton, Badge, Sheet } from "@/src/knowledge-agent/components/ui";
import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";
import type { KnowledgeEntryResultItem } from "@/src/knowledge-agent/types";
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

export function EntryResultSheet({
  item,
  onClose,
}: {
  item: KnowledgeEntryResultItem | null;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const entryId = item?.entryId ?? null;
  const entryQuery = useQuery({
    queryKey: knowledgeAgentKeys.entryCurrent(entryId as number),
    queryFn: () =>
      knowledgeAgentApi.getEntryCurrent(token as string, entryId as number),
    enabled: Boolean(token && entryId),
  });
  const current = entryQuery.data ?? null;
  const unavailable = entryQuery.isError;
  const comparable =
    item !== null &&
    current !== null &&
    item.fingerprint !== null &&
    item.fingerprint !== undefined &&
    current.fingerprint !== null &&
    current.fingerprint !== undefined;
  const changed = comparable && item!.fingerprint !== current!.fingerprint;

  return (
    <Sheet visible={item !== null} title="知识详情" onClose={onClose}>
      {item !== null && (
        <View>
          <View style={styles.head}>
            <Badge tone="confirmed">正式知识</Badge>
            <Text style={styles.path} numberOfLines={2}>
              {[item.projectName, item.nodePath].filter(Boolean).join(" / ") ||
                "归属未标注"}
            </Text>
          </View>
          <Text style={styles.title}>{item.title}</Text>
          <View style={styles.metaRow}>
            <Text style={styles.metaText}>{typeLabel(item.mainType)}</Text>
            <Text style={styles.metaDot}>·</Text>
            <Text style={styles.metaText}>{item.sourceCount} 个来源</Text>
            <Text style={styles.metaDot}>·</Text>
            <Text style={styles.metaText}>
              更新于{" "}
              {item.updatedAt ? new Date(item.updatedAt).toLocaleString() : "—"}
            </Text>
          </View>

          <Text style={styles.sectionLabel}>当前正式知识</Text>
          {entryQuery.isLoading ? (
            <View style={styles.stateBox}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.stateText}>正在读取当前知识…</Text>
            </View>
          ) : unavailable || current === null ? (
            <View style={styles.stateBox}>
              <Text style={styles.stateTitle}>该知识当前不可用</Text>
              <Text style={styles.stateText}>
                这条知识已删除、移出当前范围或权限失效；列表仍保留生成时的快照。
              </Text>
            </View>
          ) : (
            <View style={styles.entryBox}>
              {changed && (
                <View style={styles.changedBanner}>
                  <Text style={styles.changedText}>结果生成后已更新</Text>
                </View>
              )}
              {comparable && !changed && (
                <View style={styles.sameBanner}>
                  <Text style={styles.sameText}>当前内容与结果一致</Text>
                </View>
              )}
              <Text style={styles.entryContent}>{current.content}</Text>
              <Text style={styles.metaText}>
                更新于{" "}
                {current.updatedAt
                  ? new Date(current.updatedAt).toLocaleString()
                  : "—"}
              </Text>
              <Text style={styles.sectionLabel}>来源</Text>
              {(current.evidences ?? []).length > 0 ? (
                current.evidences?.map((evidence) => (
                  <View key={evidence.id} style={styles.sourceRow}>
                    <Text style={styles.sourceTitle}>
                      · {evidence.sourceTitle}
                    </Text>
                    {evidence.quote !== null && evidence.quote !== "" && (
                      <Text style={styles.sourceQuote} numberOfLines={3}>
                        “{evidence.quote}”
                      </Text>
                    )}
                  </View>
                ))
              ) : (
                <Text style={styles.metaText}>当前没有可展示的来源摘要。</Text>
              )}
            </View>
          )}
          <View style={styles.actions}>
            <AppButton label="关闭" variant="default" onPress={onClose} />
          </View>
        </View>
      )}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  head: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  path: {
    flex: 1,
    minWidth: 0,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  title: {
    marginTop: 7,
    fontSize: 17,
    lineHeight: 25,
    fontWeight: "700",
    color: theme.ink,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 6,
  },
  metaText: { color: theme.muted, fontSize: 11, lineHeight: 17 },
  metaDot: { color: theme.faint, fontSize: 11 },
  sectionLabel: {
    marginTop: 14,
    marginBottom: 5,
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  stateBox: {
    gap: 8,
    padding: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.bg,
  },
  stateTitle: { fontSize: 13, fontWeight: "700", color: theme.ink },
  stateText: { color: theme.muted, fontSize: 11, lineHeight: 18 },
  entryBox: {
    padding: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 9,
    backgroundColor: theme.soft,
  },
  changedBanner: {
    marginBottom: 8,
    padding: 8,
    borderRadius: 6,
    backgroundColor: theme.riskSoft,
  },
  changedText: { color: theme.risk, fontSize: 11, fontWeight: "600" },
  sameBanner: {
    marginBottom: 8,
    padding: 8,
    borderRadius: 6,
    backgroundColor: theme.confirmedSoft,
  },
  sameText: { color: theme.confirmed, fontSize: 11, fontWeight: "600" },
  entryContent: {
    fontSize: 13,
    lineHeight: 22,
    color: theme.ink,
  },
  sourceRow: { marginTop: 6 },
  sourceTitle: { fontSize: 12, fontWeight: "600", color: theme.ink },
  sourceQuote: {
    marginTop: 3,
    fontSize: 11,
    lineHeight: 18,
    color: theme.muted,
  },
  actions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 14,
    flexWrap: "wrap",
  },
});
