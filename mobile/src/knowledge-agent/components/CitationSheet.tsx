import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/src/auth";
import {
  AppButton,
  Sheet,
} from "@/src/knowledge-agent/components/ui";
import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";
import type { RevisionTarget } from "@/src/knowledge-agent/adapters/answer";
import type {
  KnowledgeEntryCurrent,
  KnowledgeRunCitation,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

export function CitationSheet({
  citation,
  revisionTargets,
  sourceRunId,
  onRevise,
  onClose,
}: {
  citation: KnowledgeRunCitation | null;
  revisionTargets: RevisionTarget[];
  sourceRunId: number | null;
  onRevise: (target: RevisionTarget) => void;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const revisionTarget =
    citation === null
      ? null
      : (revisionTargets.find(
          (target) => target.entryId === citation.entryId,
        ) ?? null);
  const entryId = citation?.entryId ?? null;
  const entryQuery = useQuery({
    queryKey: knowledgeAgentKeys.entryCurrent(entryId as number),
    queryFn: () =>
      knowledgeAgentApi.getEntryCurrent(token as string, entryId as number),
    enabled: Boolean(token && entryId),
  });
  const currentEntry: KnowledgeEntryCurrent | null =
    entryQuery.data ?? null;
  const entryUnavailable = entryQuery.isError;
  return (
    <Sheet
      visible={citation !== null}
      title="引用与来源"
      onClose={onClose}
    >
      {citation !== null && (
        <View>
          {/* 当前正式知识：修订动作的目标对象，展示打开弹窗时的实时内容 */}
          <Text style={styles.sectionLabel}>当前正式知识</Text>
          {entryQuery.isLoading ? (
            <View style={styles.loadingBox}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.metaText}>正在读取当前知识…</Text>
            </View>
          ) : entryUnavailable || currentEntry === null ? (
            <View style={styles.unavailableBox}>
              <Text style={styles.unavailableTitle}>该知识当前不可用</Text>
              <Text style={styles.metaText}>
                历史回答仍可查看核验原文；如需修订请重新阅读或确认对象当前状态。
              </Text>
            </View>
          ) : (
            <>
              <Text style={styles.entryTitle}>{currentEntry.title}</Text>
              <Text style={styles.path}>
                {[citation.projectName, citation.nodePath]
                  .filter(Boolean)
                  .join(" / ") || "归属未标注"}
              </Text>
              <Text style={styles.entryContent} numberOfLines={5}>
                {currentEntry.content}
              </Text>
              <Text style={styles.metaText}>
                更新于{" "}
                {currentEntry.updatedAt
                  ? new Date(currentEntry.updatedAt).toLocaleString()
                  : "—"}
              </Text>
              {revisionTarget !== null && sourceRunId !== null && (
                <Text style={styles.revisionCopy}>
                  修改这条正式知识并追加版本，确认前不会写入。
                </Text>
              )}
            </>
          )}
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>本次回答核验的原文</Text>
            <View style={styles.quoteBox}>
              <Text style={styles.quote}>“{citation.quote}”</Text>
            </View>
          </View>
          <View style={styles.section}>
            <Text style={styles.metaText}>来源：{citation.sourceTitle}</Text>
            <Text style={styles.metaText}>
              以上是回答生成时的快照，当前状态可能已变化
            </Text>
          </View>
          <View style={styles.actions}>
            {currentEntry !== null &&
              revisionTarget !== null &&
              sourceRunId !== null && (
                <AppButton
                  label="开始修订"
                  variant="ai"
                  onPress={() => onRevise(revisionTarget)}
                />
              )}
            <AppButton label="关闭" variant="default" onPress={onClose} />
          </View>
        </View>
      )}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  sectionLabel: {
    marginBottom: 5,
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  entryTitle: {
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: theme.ink,
  },
  path: { marginTop: 3, color: theme.muted, fontSize: 11, lineHeight: 17 },
  entryContent: {
    marginTop: 8,
    color: theme.ink,
    fontSize: 13,
    lineHeight: 22,
  },
  section: { marginTop: 13 },
  quoteBox: {
    marginTop: 5,
    padding: 12,
    borderLeftWidth: 3,
    borderLeftColor: theme.ai,
    backgroundColor: theme.aiSoft,
  },
  quote: { fontSize: 13, lineHeight: 22, color: theme.ink },
  metaText: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  loadingBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 8,
    padding: 10,
    borderRadius: 7,
    backgroundColor: theme.soft,
  },
  unavailableBox: {
    marginTop: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 7,
    backgroundColor: theme.bg,
  },
  unavailableTitle: { fontSize: 12, fontWeight: "700", color: theme.ink },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 14,
    flexWrap: "wrap",
  },
  revisionCopy: {
    marginTop: 8,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
});
