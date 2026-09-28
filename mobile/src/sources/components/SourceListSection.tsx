/** 「最近收集」区块：标题行、全部 / 未归属筛选、列表与加载 / 空 / 失败三态。 */

import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import type { Project } from "@/src/api";
import { AppButton, Card, CardBody } from "@/src/knowledge-agent/components/ui";
import { SourceIcon } from "@/src/sources/components/SourceIcon";
import { SourceRow } from "@/src/sources/components/SourceRow";
import { hasActiveSources } from "@/src/sources/state";
import type { SourceFilter, SourceOut } from "@/src/sources/types";
import { theme } from "@/src/theme";

const FILTERS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "unassigned", label: "未归属" },
];

export function SourceListSection({
  sources,
  projects,
  filter,
  onFilterChange,
  isPending,
  errorText,
  isRefreshing,
  movingIds,
  onRefresh,
  onReload,
  onOpenSource,
  onRetrySource,
  onStartCapture,
}: {
  sources: SourceOut[];
  projects: Project[];
  filter: SourceFilter;
  onFilterChange: (filter: SourceFilter) => void;
  isPending: boolean;
  errorText: string | null;
  isRefreshing: boolean;
  movingIds: number[];
  onRefresh: () => void;
  onReload: () => void;
  onOpenSource: (sourceId: number) => void;
  onRetrySource: (sourceId: number) => void;
  onStartCapture: () => void;
}) {
  const isError = errorText !== null;
  const showList = !isError && !isPending;
  const meta = (() => {
    if (isError) return { text: "加载失败", alert: true };
    if (isPending) return { text: "读取中…", alert: false };
    if (isRefreshing) return { text: "刷新中…", alert: false };
    if (sources.length === 0) return { text: "0 条", alert: false };
    const active = sources.filter(
      (source) => source.status === "waiting" || source.status === "processing",
    ).length;
    return active ? { text: `${active} 条等待或处理中`, alert: false } : { text: "下拉刷新", alert: false };
  })();

  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <Text style={styles.headTitle}>最近收集</Text>
        <Text style={[styles.headMeta, meta.alert && styles.headMetaAlert]} numberOfLines={1}>
          {meta.text}
        </Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="刷新来源列表"
          onPress={onRefresh}
          style={({ pressed }) => [styles.refresh, pressed && styles.pressed]}
        >
          <SourceIcon name="refresh" size={17} color={theme.muted} />
        </Pressable>
      </View>

      <View style={styles.filters} accessibilityRole="tablist">
        {FILTERS.map((item) => {
          const selected = item.value === filter;
          return (
            <Pressable
              key={item.value}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              accessibilityLabel={item.label}
              onPress={() => onFilterChange(item.value)}
              style={({ pressed }) => [styles.filter, pressed && styles.pressed]}
            >
              <Text style={[styles.filterText, selected && styles.filterTextActive]}>
                {item.label}
              </Text>
              {selected ? <View style={styles.filterUnderline} /> : null}
            </Pressable>
          );
        })}
      </View>

      {isPending ? (
        <Card>
          <CardBody>
            <View style={styles.loading}>
              <ActivityIndicator color={theme.green} />
              <Text style={styles.stateText}>正在读取最近收集…</Text>
            </View>
          </CardBody>
        </Card>
      ) : null}

      {isError ? (
        <Card accent="risk">
          <CardBody>
            <View style={styles.stateBody}>
              <SourceIcon name="cloudOff" size={22} color={theme.error} />
              <Text style={styles.stateTitle}>来源列表加载失败</Text>
              <Text style={styles.stateText}>
                网络连接不稳定，列表没有取到最新数据。已经提交的材料不会丢失，网络恢复后重新加载即可。
              </Text>
              <Text style={styles.stateDetail}>{errorText}</Text>
              <AppButton label="重新加载" onPress={onReload} />
            </View>
          </CardBody>
        </Card>
      ) : null}

      {showList && sources.length === 0 ? (
        <Card>
          <CardBody>
            <View style={styles.stateBody}>
              <SourceIcon name="sprout" size={24} color={theme.green} />
              <Text style={styles.stateTitle}>
                {filter === "unassigned" ? "没有未归属来源" : "还没有来源"}
              </Text>
              <Text style={styles.stateText}>
                用上面的入口采集第一条材料。处理完成后，原始材料、OCR 文本和 AI 候选都会出现在来源详情里。
              </Text>
              <AppButton label="从相册采集" variant="primary" onPress={onStartCapture} />
            </View>
          </CardBody>
        </Card>
      ) : null}

      {showList && sources.length > 0 ? (
        <View style={styles.list}>
          {sources.map((source, index) => (
            <SourceRow
              key={source.id}
              source={source}
              projects={projects}
              moving={movingIds.includes(source.id)}
              last={index === sources.length - 1}
              onOpen={onOpenSource}
              onRetry={onRetrySource}
            />
          ))}
        </View>
      ) : null}

      {hasActiveSources(sources) ? (
        <Text style={styles.pollHint}>处理在后台进行，列表会自动刷新；不用一直停在这一页。</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  section: { marginTop: 18 },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  headTitle: { fontSize: 15, fontWeight: "700", color: theme.ink },
  headMeta: { flex: 1, fontSize: 11, color: theme.muted },
  headMetaAlert: { color: theme.error, fontWeight: "600" },
  refresh: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  filters: { marginTop: 10, flexDirection: "row", gap: 18 },
  filter: { flexDirection: "row", alignItems: "center", gap: 5, paddingBottom: 4 },
  filterText: { fontSize: 12.5, fontWeight: "600", color: theme.muted },
  filterTextActive: { color: theme.green },
  filterUnderline: {
    position: "absolute",
    right: 0,
    bottom: 0,
    left: 0,
    height: 2,
    borderRadius: 2,
    backgroundColor: theme.green,
  },
  list: {
    marginTop: 12,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 10,
    backgroundColor: theme.surface,
  },
  loading: { flexDirection: "row", alignItems: "center", gap: 10 },
  stateBody: { alignItems: "center", gap: 8 },
  stateTitle: { fontSize: 13.5, fontWeight: "700", color: theme.ink, textAlign: "center" },
  stateText: { fontSize: 12, lineHeight: 19, color: theme.muted, textAlign: "center" },
  stateDetail: { fontSize: 11.5, lineHeight: 18, color: theme.error, textAlign: "center" },
  pollHint: { marginTop: 10, fontSize: 11, lineHeight: 17, color: theme.muted },
  pressed: { opacity: 0.85 },
});
