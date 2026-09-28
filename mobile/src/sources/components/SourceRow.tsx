/** 最近收集列表的单行：类型、标题、附件与时间、状态徽标、归属与副状态、失败重试。 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { Project } from "@/src/api";
import { Badge } from "@/src/knowledge-agent/components/ui";
import { SourceIcon, type SourceIconName } from "@/src/sources/components/SourceIcon";
import {
  failureLine,
  formatSourceTime,
  needsProcessingRetry,
  retryLabel,
  sourceKind,
  sourceMaterialSummary,
  sourceProjectLabel,
  sourceStatusBadge,
  sourceSubStatus,
} from "@/src/sources/state";
import type { SourceOut } from "@/src/sources/types";
import { theme } from "@/src/theme";

function Tag({ icon, label, tone }: { icon: SourceIconName; label: string; tone: "neutral" | "confirmed" }) {
  const color = tone === "confirmed" ? theme.confirmed : theme.muted;
  return (
    <View style={styles.tag}>
      <SourceIcon name={icon} size={12} color={color} strokeWidth={1.8} />
      <Text style={[styles.tagText, { color }]}>{label}</Text>
    </View>
  );
}

export function SourceRow({
  source,
  projects,
  moving,
  last,
  onOpen,
  onRetry,
}: {
  source: SourceOut;
  projects: Project[];
  moving: boolean;
  last: boolean;
  onOpen: (sourceId: number) => void;
  onRetry: (sourceId: number) => void;
}) {
  const badge = sourceStatusBadge(source);
  const subStatus = sourceSubStatus(source);
  const failure = failureLine(source);
  const retry = needsProcessingRetry(source);
  const kind = sourceKind(source);
  const projectLabel = sourceProjectLabel(source, projects);

  return (
    <View style={[styles.row, !last && styles.rowDivider]} testID={`source-row-${source.id}`}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`查看来源详情：${source.title}`}
        onPress={() => onOpen(source.id)}
        style={({ pressed }) => [styles.open, pressed && styles.pressed]}
      >
        <View style={styles.icon}>
          <SourceIcon name={kind === "text" ? "text" : "image"} size={18} color={theme.green} />
        </View>
        <View style={styles.main}>
          <Text style={styles.title} numberOfLines={2}>
            {source.title}
          </Text>
          <Text style={styles.meta} numberOfLines={1}>
            {sourceMaterialSummary(source)} · {formatSourceTime(source.created_at)}
          </Text>
        </View>
        <Badge tone={badge.tone}>{badge.label}</Badge>
      </Pressable>

      <View style={styles.tags}>
        <Tag
          icon={source.project_id === null ? "info" : "folder"}
          label={projectLabel}
          tone="neutral"
        />
        {subStatus ? (
          <Badge tone={subStatus.tone}>
            {subStatus.label}
          </Badge>
        ) : null}
        {moving ? <Badge tone="ai">更换项目中</Badge> : null}
      </View>

      {failure ? (
        <View style={styles.error}>
          <SourceIcon name="alert" size={14} color={theme.error} />
          <Text style={styles.errorText}>{failure}</Text>
        </View>
      ) : null}

      {retry ? (
        <View style={styles.actions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${retryLabel(source)}：${source.title}`}
            onPress={() => onRetry(source.id)}
            style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
          >
            <SourceIcon name="refresh" size={15} color={theme.ink} />
            <Text style={styles.retryText}>{retryLabel(source)}</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { paddingHorizontal: 13, paddingVertical: 11, backgroundColor: theme.surface },
  rowDivider: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: theme.border },
  open: { flexDirection: "row", alignItems: "center", gap: 10 },
  icon: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.greenSoft,
  },
  main: { flex: 1, gap: 3 },
  title: { fontSize: 13.5, lineHeight: 20, fontWeight: "600", color: theme.ink },
  meta: { fontSize: 11, lineHeight: 17, color: theme.muted },
  tags: { marginTop: 8, flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 6 },
  tag: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    backgroundColor: theme.soft,
  },
  tagText: { fontSize: 10, lineHeight: 16, fontWeight: "600" },
  error: { marginTop: 8, flexDirection: "row", alignItems: "flex-start", gap: 5 },
  errorText: { flex: 1, fontSize: 11.5, lineHeight: 18, color: theme.error },
  actions: { marginTop: 9, flexDirection: "row" },
  retry: {
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 13,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  retryText: { fontSize: 12.5, fontWeight: "600", color: theme.ink },
  pressed: { opacity: 0.85 },
});
