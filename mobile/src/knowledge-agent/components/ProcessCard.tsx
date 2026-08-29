import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { Badge, Card, CardBody, Eyebrow } from "@/src/knowledge-agent/components/ui";
import { presentRunStep } from "@/src/knowledge-agent/adapters/steps";
import type { KnowledgeRun } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

export function ProcessCard({
  run,
  scopeLabel,
  cancelling,
  pollingError,
  onCancel,
  onRetryPolling,
}: {
  run: KnowledgeRun;
  scopeLabel: string;
  cancelling: boolean;
  pollingError: string | null;
  onCancel: () => void;
  onRetryPolling: () => void;
}) {
  const step = presentRunStep(run);
  const eyebrow =
    run.scopeType === "project" ? "检索项目知识" : "检索 Workspace 知识";
  return (
    <Card>
      <CardBody>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="search" size={14} color={theme.muted} />}>
              {eyebrow}
            </Eyebrow>
            <Text style={styles.title}>{step.title}</Text>
          </View>
          <Badge tone={pollingError !== null ? "error" : "neutral"}>
            {cancelling
              ? "正在取消"
              : pollingError !== null
                ? "状态异常"
                : "进行中"}
          </Badge>
        </View>
        <View style={styles.scopeRow}>
          <AgentIcon name="folder" size={14} color={theme.muted} />
          <Text style={styles.scopeText}>检索范围：{scopeLabel}</Text>
        </View>
        {pollingError !== null && (
          <View style={styles.pollingErrorBox}>
            <Text style={styles.pollingErrorText}>状态更新失败：{pollingError}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="重试获取回答状态"
              onPress={onRetryPolling}
              style={({ pressed }) => [
                styles.cancel,
                pressed && styles.cancelPressed,
              ]}
            >
              <Text style={styles.cancelText}>重试</Text>
            </Pressable>
          </View>
        )}
        {!cancelling && pollingError === null && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="取消当前回答"
            onPress={onCancel}
            style={({ pressed }) => [styles.cancel, pressed && styles.cancelPressed]}
          >
            <Text style={styles.cancelText}>取消</Text>
          </Pressable>
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
  scopeText: {
    color: theme.muted,
    fontSize: 10,
    lineHeight: 16,
  },
  cancel: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  cancelPressed: { opacity: 0.9 },
  cancelText: { fontSize: 13, fontWeight: "600", color: theme.ink },
  pollingErrorBox: { marginTop: 12 },
  pollingErrorText: {
    color: theme.error,
    fontSize: 12,
    lineHeight: 19,
    marginBottom: 8,
  },
});
