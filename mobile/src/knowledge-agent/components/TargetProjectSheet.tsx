import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { Sheet } from "@/src/knowledge-agent/components/ui";
import { theme } from "@/src/theme";

export interface DraftTargetOption {
  id: number;
  name: string | null;
}

/** Workspace 多项目回答的目标项目选择：只列项目，不展示目录节点。 */
export function TargetProjectSheet({
  visible,
  options,
  sourceRunId,
  submitting,
  error,
  onSelect,
  onClose,
}: {
  visible: boolean;
  options: DraftTargetOption[];
  sourceRunId: number | null;
  submitting: boolean;
  error: string | null;
  onSelect: (sourceRunId: number, projectId: number) => void;
  onClose: () => void;
}) {
  return (
    <Sheet visible={visible} title="选择目标项目" onClose={onClose}>
      <Text style={styles.intro}>
        回答命中了多个项目。草稿只采用所选项目的证据，不会跨项目综合写入。
      </Text>
      {error !== null && <Text style={styles.error}>{error}</Text>}
      {options.map((option) => (
        <Pressable
          key={option.id}
          accessibilityRole="button"
          accessibilityLabel={`整理到项目：${option.name ?? "未命名项目"}`}
          disabled={submitting}
          onPress={() => {
            if (sourceRunId !== null) onSelect(sourceRunId, option.id);
          }}
          style={({ pressed }) => [
            styles.option,
            submitting && styles.optionDisabled,
            pressed && !submitting && styles.pressed,
          ]}
        >
          <View style={styles.optionIcon}>
            <AgentIcon name="folder" size={18} color={theme.green} />
          </View>
          <View style={styles.optionMain}>
            <Text style={styles.optionTitle}>{option.name ?? "未命名项目"}</Text>
            <Text style={styles.optionDetail}>以此项目为整理目标</Text>
          </View>
          <AgentIcon name="chevron" size={18} color={theme.muted} />
        </Pressable>
      ))}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  intro: {
    color: theme.muted,
    fontSize: 12,
    lineHeight: 19,
    marginBottom: 10,
  },
  error: { color: theme.error, fontSize: 12, lineHeight: 18, marginBottom: 8 },
  option: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  optionDisabled: { opacity: 0.5 },
  optionIcon: {
    width: 30,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 7,
    backgroundColor: theme.greenSoft,
  },
  optionMain: { minWidth: 0, flex: 1 },
  optionTitle: { fontSize: 13, fontWeight: "600", color: theme.ink },
  optionDetail: { marginTop: 2, color: theme.muted, fontSize: 10 },
  pressed: { opacity: 0.85 },
});
