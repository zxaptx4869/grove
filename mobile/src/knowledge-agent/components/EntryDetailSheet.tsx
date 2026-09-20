import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/src/auth";
import { knowledgeAgentApi } from "@/src/knowledge-agent/api";
import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { RichText } from "@/src/knowledge-agent/components/RichText";
import { AppButton, Badge, Sheet } from "@/src/knowledge-agent/components/ui";
import { classifyKnowledgeAgentError } from "@/src/knowledge-agent/errors";
import { useReducedMotion } from "@/src/knowledge-agent/hooks/useReducedMotion";
import { knowledgeAgentKeys } from "@/src/knowledge-agent/queryKeys";
import { theme } from "@/src/theme";

export interface EntryDetailTarget {
  entryId: number;
  title: string;
  projectName: string | null;
  nodePath: string | null;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString();
}

export function EntryDetailSheet({
  target,
  onClose,
}: {
  target: EntryDetailTarget | null;
  onClose: () => void;
}) {
  const { token } = useAuth();
  const reducedMotion = useReducedMotion();
  const entryId = target?.entryId ?? 0;
  const query = useQuery({
    queryKey: knowledgeAgentKeys.entryCurrent(entryId),
    queryFn: () => knowledgeAgentApi.getEntryCurrent(token as string, entryId),
    enabled: Boolean(token && target),
  });
  const error = query.isError ? classifyKnowledgeAgentError(query.error) : null;
  const unavailable = error?.kind === "not_found" || error?.kind === "auth";
  const current = query.data ?? null;
  const path = [target?.projectName, target?.nodePath ?? current?.nodeName]
    .filter(Boolean)
    .join(" / ");

  return (
    <Sheet
      visible={target !== null}
      title="知识详情"
      onClose={onClose}
      presentation="bottom"
      reduceMotion={reducedMotion}
    >
      {target ? (
        <View>
          <View style={styles.headingRow}>
            <Badge tone="confirmed">正式知识</Badge>
            {path ? (
              <Text style={styles.path} numberOfLines={2}>
                {path}
              </Text>
            ) : null}
          </View>
          <Text style={styles.title}>{current?.title || target.title}</Text>

          {query.isLoading ? (
            <View style={styles.stateBox} accessibilityRole="progressbar">
              <ActivityIndicator color={theme.green} />
              <Text style={styles.stateText}>正在读取当前知识…</Text>
            </View>
          ) : error || !current ? (
            <View style={styles.stateBox} accessibilityRole="alert">
              <Text style={styles.stateTitle}>
                {unavailable ? "该知识当前不可访问" : "当前知识读取失败"}
              </Text>
              <Text style={styles.stateText}>
                {unavailable
                  ? "这条历史结果仍会保留，但当前正文可能已删除、移出范围或不可访问。"
                  : error?.message ?? "暂时无法读取当前知识。"}
              </Text>
              {!unavailable ? (
                <AppButton
                  label="重试读取"
                  onPress={() => void query.refetch()}
                  icon={<AgentIcon name="retry" size={15} color={theme.ink} />}
                />
              ) : null}
            </View>
          ) : (
            <View>
              <Text style={styles.updatedAt}>更新于 {formatTime(current.updatedAt)}</Text>
              <View style={styles.content}>
                <RichText>{current.content || "当前正文为空。"}</RichText>
              </View>

              <Text style={styles.sectionLabel}>关联来源</Text>
              {(current.evidences ?? []).length > 0 ? (
                current.evidences?.map((evidence) => (
                  <View key={evidence.id} style={styles.sourceRow}>
                    <Text style={styles.sourceTitle}>{evidence.sourceTitle}</Text>
                    {evidence.quote ? (
                      <View style={styles.sourceQuote}>
                        <RichText tone="muted">{evidence.quote}</RichText>
                      </View>
                    ) : null}
                  </View>
                ))
              ) : (
                <Text style={styles.stateText}>当前没有可展示的来源摘要。</Text>
              )}
            </View>
          )}
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  headingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  path: { flex: 1, minWidth: 0, color: theme.muted, fontSize: 12, lineHeight: 18 },
  title: {
    marginTop: 9,
    color: theme.ink,
    fontSize: 18,
    lineHeight: 26,
    fontWeight: "700",
  },
  stateBox: {
    marginTop: 16,
    gap: 10,
    padding: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  stateTitle: { color: theme.ink, fontSize: 14, fontWeight: "700" },
  stateText: { color: theme.muted, fontSize: 13, lineHeight: 21 },
  sectionLabel: {
    marginTop: 18,
    color: theme.confirmed,
    fontSize: 12,
    lineHeight: 18,
    fontWeight: "700",
  },
  updatedAt: { marginTop: 5, color: theme.muted, fontSize: 11, lineHeight: 17 },
  content: { marginTop: 10 },
  sourceRow: { marginTop: 10 },
  sourceTitle: { color: theme.muted, fontSize: 12, lineHeight: 19, fontWeight: "500" },
  sourceQuote: { marginTop: 3 },
});
