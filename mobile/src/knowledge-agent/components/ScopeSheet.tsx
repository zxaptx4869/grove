import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { Sheet } from "@/src/knowledge-agent/components/ui";
import type { Project } from "@/src/api";
import type {
  KnowledgeScopeChangeRequest,
  KnowledgeScopeType,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

export function ScopeSheet({
  visible,
  current,
  projects,
  loadingProjects,
  projectsError,
  disabled,
  disabledNote,
  onChange,
  onClose,
}: {
  visible: boolean;
  current: KnowledgeScopeChangeRequest;
  projects: Project[] | undefined;
  loadingProjects: boolean;
  projectsError: string | null;
  disabled: boolean;
  disabledNote: string | null;
  onChange: (scope: KnowledgeScopeChangeRequest) => void;
  onClose: () => void;
}) {
  const isSelected = (scopeType: KnowledgeScopeType, projectId?: number | null) =>
    current.scopeType === scopeType &&
    (current.projectId ?? null) === (projectId ?? null);
  return (
    <Sheet visible={visible} title="当前知识范围" onClose={onClose}>
      {disabled && disabledNote !== null && (
        <Text style={styles.disabledNote}>{disabledNote}</Text>
      )}
      <ScopeOption
        icon="book"
        title="全部知识"
        detail="当前 Workspace 的所有正式知识"
        selected={isSelected("workspace")}
        disabled={disabled}
        onPress={() => onChange({ scopeType: "workspace", projectId: null })}
      />
      {loadingProjects && <Text style={styles.hint}>正在加载项目…</Text>}
      {projectsError !== null && (
        <Text style={styles.error}>项目加载失败：{projectsError}</Text>
      )}
      {projects?.map((project) => (
        <ScopeOption
          key={project.id}
          icon="folder"
          title={project.name}
          detail="项目内全部正式知识"
          selected={isSelected("project", project.id)}
          disabled={disabled}
          onPress={() =>
            onChange({
              scopeType: "project",
              projectId: project.id,
              projectName: project.name,
            })
          }
        />
      ))}
      {!loadingProjects && projects?.length === 0 && (
        <Text style={styles.hint}>当前 Workspace 尚无项目，只有「全部知识」。</Text>
      )}
    </Sheet>
  );
}

function ScopeOption({
  icon,
  title,
  detail,
  selected,
  disabled,
  onPress,
}: {
  icon: "book" | "folder";
  title: string;
  detail: string;
  selected: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      accessibilityLabel={`${title}（${detail}）`}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.option,
        disabled && styles.optionDisabled,
        pressed && !disabled && styles.pressed,
      ]}
    >
      <View style={[styles.optionIcon, selected && styles.optionIconActive]}>
        <AgentIcon
          name={icon}
          size={18}
          color={selected ? theme.green : theme.muted}
        />
      </View>
      <View style={styles.optionMain}>
        <Text style={[styles.optionTitle, selected && styles.optionTitleActive]}>
          {title}
        </Text>
        <Text style={styles.optionDetail}>{detail}</Text>
      </View>
      {selected && <AgentIcon name="check" size={18} color={theme.green} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  disabledNote: {
    color: theme.risk,
    fontSize: 12,
    lineHeight: 20,
    marginBottom: 8,
  },
  option: {
    minHeight: 58,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  optionDisabled: { opacity: 0.48 },
  pressed: { opacity: 0.85 },
  optionIcon: {
    width: 30,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  optionIconActive: { backgroundColor: theme.greenSoft },
  optionMain: { flex: 1, minWidth: 0 },
  optionTitle: { fontSize: 13, fontWeight: "600", color: theme.ink },
  optionTitleActive: { color: theme.green },
  optionDetail: { marginTop: 2, color: theme.muted, fontSize: 10 },
  hint: { color: theme.muted, paddingVertical: 18, fontSize: 12 },
  error: { color: theme.error, paddingVertical: 18, fontSize: 12 },
});
