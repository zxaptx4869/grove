import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AppButton } from "@/src/knowledge-agent/components/ui";
import { useReducedMotion } from "@/src/knowledge-agent/hooks/useReducedMotion";
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
  cancelling,
  pollingError,
  cancelError,
  onCancel,
  onRetryPolling,
}: {
  run: KnowledgeRun;
  cancelling: boolean;
  pollingError: string | null;
  cancelError: string | null;
  onCancel: () => void;
  onRetryPolling: () => void;
}) {
  const reducedMotion = useReducedMotion();
  const stage = run.dialogueStage
    ? STAGE_LABELS[run.dialogueStage] ?? "正在处理"
    : run.status === "waiting"
      ? "等待执行"
      : "正在准备本轮回答";
  return (
    <View style={styles.root}>
      <View style={styles.head} accessibilityRole="progressbar">
        {reducedMotion ? (
          <View testID="agent-stage-static">
            <AgentIcon name="message" size={16} color={theme.ai} />
          </View>
        ) : (
          <ActivityIndicator testID="agent-stage-spinner" size="small" color={theme.ai} />
        )}
        <Text style={styles.title}>{cancelling ? "正在取消" : stage}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={cancelling ? "正在取消回答" : "停止当前回答"}
          accessibilityState={{ disabled: cancelling }}
          disabled={cancelling}
          onPress={onCancel}
          style={({ pressed }) => [
            styles.stopButton,
            cancelling && styles.stopButtonDisabled,
            pressed && !cancelling && styles.pressed,
          ]}
        >
          <AgentIcon name="stop" size={20} color={theme.ink} />
        </Pressable>
      </View>
      {pollingError ? (
        <View style={styles.errorBox} accessibilityRole="alert">
          <Text style={styles.errorTitle}>连接中断，服务端状态未知</Text>
          <Text style={styles.errorCopy}>{pollingError}</Text>
          <AppButton
            label="刷新状态"
            variant="ghost"
            onPress={onRetryPolling}
            icon={<AgentIcon name="retry" size={15} color={theme.ink} />}
          />
        </View>
      ) : null}
      {cancelError ? (
        <View style={styles.errorBox} accessibilityRole="alert">
          <Text style={styles.errorTitle}>取消请求未完成</Text>
          <Text style={styles.errorCopy}>{cancelError}</Text>
          <AppButton label="重试取消" variant="ghost" onPress={onCancel} />
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { marginBottom: 12 },
  head: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingLeft: 3,
  },
  title: { flex: 1, minWidth: 0, color: theme.muted, fontSize: 13, lineHeight: 20 },
  stopButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
  },
  stopButtonDisabled: { opacity: 0.48 },
  errorBox: {
    marginTop: 6,
    gap: 7,
    padding: 10,
    borderRadius: 8,
    backgroundColor: theme.errorSoft,
  },
  errorTitle: { color: theme.error, fontSize: 12, fontWeight: "700" },
  errorCopy: { color: theme.muted, fontSize: 11, lineHeight: 18 },
  pressed: { backgroundColor: theme.soft },
});
