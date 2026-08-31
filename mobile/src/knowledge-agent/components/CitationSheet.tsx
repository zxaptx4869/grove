import { StyleSheet, Text, View } from "react-native";

import {
  AppButton,
  Badge,
  Sheet,
} from "@/src/knowledge-agent/components/ui";
import type { RevisionTarget } from "@/src/knowledge-agent/adapters/answer";
import type { KnowledgeRunCitation } from "@/src/knowledge-agent/types";
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
  const revisionTarget =
    citation === null
      ? null
      : (revisionTargets.find(
          (target) => target.entryId === citation.entryId,
        ) ?? null);
  return (
    <Sheet
      visible={citation !== null}
      title="引用与来源"
      onClose={onClose}
    >
      {citation !== null && (
        <View>
          <Badge tone="confirmed">对应正式 Entry · 本次回答核验</Badge>
          <Text style={styles.entryTitle}>{citation.entryTitle}</Text>
          <Text style={styles.path}>
            {[citation.projectName, citation.nodePath]
              .filter(Boolean)
              .join(" / ") || "归属未标注"}
          </Text>
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>本次回答核验的 SOURCE 原文</Text>
            <View style={styles.quoteBox}>
              <Text style={styles.quote}>“{citation.quote}”</Text>
            </View>
          </View>
          <View style={styles.meta}>
            <Text style={styles.metaText}>来源：{citation.sourceTitle}</Text>
            <Text style={styles.metaText}>
              以上是回答生成时的快照，当前状态可能已变化
            </Text>
          </View>
          {revisionTarget !== null && sourceRunId !== null && (
            <View style={styles.revisionBox}>
              <Text style={styles.revisionTitle}>修订这条知识</Text>
              <Text style={styles.revisionCopy}>
                将修改这条正式知识并追加版本；只采用本次回答核验的来源，
                确认前不会写入。
              </Text>
              <AppButton
                label="开始修订"
                variant="ai"
                onPress={() => onRevise(revisionTarget)}
              />
            </View>
          )}
          <View style={styles.actions}>
            <AppButton label="查看当前知识（暂不可用）" disabled onPress={() => {}} />
            <AppButton label="关闭" variant="ghost" onPress={onClose} />
          </View>
        </View>
      )}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  entryTitle: {
    marginTop: 8,
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: theme.ink,
  },
  path: { marginTop: 4, color: theme.muted, fontSize: 11, lineHeight: 17 },
  section: { marginTop: 13 },
  sectionLabel: {
    marginBottom: 5,
    color: theme.muted,
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  quoteBox: {
    padding: 12,
    borderLeftWidth: 3,
    borderLeftColor: theme.ai,
    backgroundColor: theme.aiSoft,
  },
  quote: { fontSize: 13, lineHeight: 22, color: theme.ink },
  meta: {
    gap: 7,
    marginTop: 13,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  metaText: {
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  actions: { marginTop: 14, gap: 8 },
  revisionBox: {
    marginTop: 14,
    padding: 11,
    borderWidth: 1,
    borderColor: "#DACCDE",
    borderRadius: 9,
    backgroundColor: theme.aiSoft,
    gap: 6,
  },
  revisionTitle: { fontSize: 12, fontWeight: "700", color: theme.ai },
  revisionCopy: {
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
});
