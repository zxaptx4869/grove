/** 所属项目选择：默认未归属，选项来自 /api/projects。 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Project } from "@/src/api";
import { Sheet } from "@/src/knowledge-agent/components/ui";
import { theme } from "@/src/theme";

export function ProjectSheet({
  visible,
  projects,
  selectedId,
  onSelect,
  onClose,
}: {
  visible: boolean;
  projects: Project[];
  selectedId: number | null;
  onSelect: (projectId: number | null) => void;
  onClose: () => void;
}) {
  const options: { id: number | null; name: string }[] = [
    { id: null, name: "未归属" },
    ...projects.map((project) => ({ id: project.id, name: project.name })),
  ];
  return (
    <Sheet visible={visible} title="所属项目" onClose={onClose}>
      {options.map((option) => {
        const selected = option.id === selectedId;
        return (
          <Pressable
            key={option.id ?? "none"}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={option.name}
            onPress={() => onSelect(option.id)}
            style={({ pressed }) => [
              styles.option,
              selected && styles.optionSelected,
              pressed && styles.pressed,
            ]}
          >
            <Text style={[styles.optionText, selected && styles.optionTextSelected]}>
              {option.name}
            </Text>
            <View style={[styles.radio, selected && styles.radioSelected]}>
              {selected ? <View style={styles.radioDot} /> : null}
            </View>
          </Pressable>
        );
      })}
      <Text style={styles.footnote}>默认未归属，之后可在桌面工作台改归属。</Text>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  option: {
    minHeight: 48,
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  optionSelected: { borderColor: "#BAD5C5", backgroundColor: theme.greenSoft },
  optionText: { flex: 1, fontSize: 13, fontWeight: "600", color: theme.ink },
  optionTextSelected: { color: theme.green },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: theme.border,
    alignItems: "center",
    justifyContent: "center",
  },
  radioSelected: { borderColor: theme.green },
  radioDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: theme.green },
  footnote: { marginTop: 14, fontSize: 11, lineHeight: 18, color: theme.muted },
  pressed: { opacity: 0.85 },
});
