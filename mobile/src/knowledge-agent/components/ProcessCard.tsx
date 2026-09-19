import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AppButton, Card, CardBody } from "@/src/knowledge-agent/components/ui";
import type { KnowledgeRun } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const STAGE_LABELS: Record<string, string> = {
  organizing: "正在组织回答",
  querying: "正在查询知识库",
  reading_entries: "正在读取知识",
  reading_sources: "正在核验来源",
  finalizing: "正在整理回答",
};

export function ProcessCard({
  run,
  scopeLabel,
  cancelling,
  pollingError,
  cancelError,
  onCancel,
  onRetryPolling,
}: {
  run: KnowledgeRun;
  scopeLabel: string;
  cancelling: boolean;
  pollingError: string | null;
  cancelError: string | null;
  onCancel: () => void;
  onRetryPolling: () => void;
}) {
  const stage = run.dialogueStage
    ? STAGE_LABELS[run.dialogueStage] ?? "正在处理"
    : run.status === "waiting"
      ? "等待执行"
      : "正在准备本轮回答";
  return (
    <Card>
      <CardBody>
        <View style={styles.head} accessibilityRole="progressbar">
          <ActivityIndicator color={theme.ai} />
          <View style={styles.main}>
            <Text style={styles.title}>{cancelling ? "正在取消" : stage}</Text>
            <Text style={styles.copy}>范围：{scopeLabel}</Text>
          </View>
        </View>
        {pollingError ? (
          <View style={styles.errorBox} accessibilityRole="alert">
            <Text style={styles.errorTitle}>连接中断，服务端状态未知</Text>
            <Text style={styles.errorCopy}>{pollingError}</Text>
            <AppButton
              label="刷新状态"
              onPress={onRetryPolling}
              icon={<AgentIcon name="retry" size={15} color={theme.ink} />}
            />
          </View>
        ) : null}
        {cancelError ? (
          <View style={styles.errorBox} accessibilityRole="alert">
            <Text style={styles.errorTitle}>取消请求未完成</Text>
            <Text style={styles.errorCopy}>{cancelError}</Text>
          </View>
        ) : null}
        <View style={styles.actions}>
          <AppButton
            label={cancelling ? "正在取消" : "取消回答"}
            variant="danger"
            disabled={cancelling}
            onPress={onCancel}
          />
        </View>
      </CardBody>
    </Card>
  );
}

const styles = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  main: { flex: 1, minWidth: 0 },
  title: { color: theme.ink, fontSize: 14, fontWeight: "700" },
  copy: { marginTop: 3, color: theme.muted, fontSize: 11 },
  errorBox: {
    marginTop: 11,
    gap: 7,
    padding: 10,
    borderRadius: 8,
    backgroundColor: theme.errorSoft,
  },
  errorTitle: { color: theme.error, fontSize: 12, fontWeight: "700" },
  errorCopy: { color: theme.muted, fontSize: 11, lineHeight: 18 },
  actions: { marginTop: 12, alignItems: "flex-start" },
});
