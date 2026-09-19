import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import type { EntryDetailTarget } from "@/src/knowledge-agent/components/EntryDetailSheet";
import { AppButton, Badge, Card, CardBody } from "@/src/knowledge-agent/components/ui";
import type {
  KnowledgeAnswerBlock,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";
import { dialogueStatusOf } from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  partial_completed: "部分完成",
  failed: "失败",
  cancelled: "已取消",
  not_executed: "未执行",
  unsupported: "暂不支持",
};

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function listSubject(block: KnowledgeAnswerBlock): string {
  if (block.resultType === "projects" || block.semantics?.subject === "projects") {
    return "projects";
  }
  if (block.resultType === "directories" || block.semantics?.subject === "directories") {
    return "directories";
  }
  if (block.resultType === "entries" || block.semantics?.subject === "entries") {
    return "entries";
  }
  return "unknown";
}

function listTitle(block: KnowledgeAnswerBlock, subject: string): string {
  if (block.label) return block.label;
  if (subject === "projects") return "当前 Workspace 可访问项目";
  if (subject === "directories") {
    return `${block.semantics?.projectName ?? "当前项目"} · ${
      block.semantics?.displayName ?? "项目目录"
    }`;
  }
  if (subject === "entries") return "正式知识列表";
  return "结果列表";
}

function itemTitle(item: Record<string, unknown>, index: number): string {
  return (
    stringValue(item.name) ??
    stringValue(item.title) ??
    stringValue(item.label) ??
    `第 ${index + 1} 项`
  );
}

function itemPath(item: Record<string, unknown>): string | null {
  const project = stringValue(item.projectName);
  const path = stringValue(item.path) ?? stringValue(item.nodePath);
  return [project, path].filter(Boolean).join(" / ") || null;
}

function itemSummary(item: Record<string, unknown>): string | null {
  return stringValue(item.summary) ?? stringValue(item.excerpt);
}

function relevanceLabel(value: string | null): string | null {
  if (value === "direct") return "直接相关";
  if (value === "indirect") return "间接相关";
  if (value === "unrelated") return "不相关";
  return value;
}

function StatusNotice({ run }: { run: KnowledgeRun }) {
  const status = dialogueStatusOf(run);
  if (status === "completed") return null;
  const risk = status === "partial_completed" || status === "not_executed";
  return (
    <View style={[styles.notice, !risk && styles.noticeError]} accessibilityRole="alert">
      <AgentIcon name="alert" size={15} color={risk ? theme.risk : theme.error} />
      <View style={styles.noticeMain}>
        <Text style={[styles.noticeTitle, !risk && styles.noticeErrorText]}>
          {STATUS_LABELS[status] ?? "本轮未完整完成"}
        </Text>
        {run.error ? <Text style={styles.noticeCopy}>{run.error}</Text> : null}
      </View>
    </View>
  );
}

function ListItem({
  item,
  index,
  expandable,
  onOpenEntry,
}: {
  item: Record<string, unknown>;
  index: number;
  expandable: boolean;
  onOpenEntry: (target: EntryDetailTarget) => void;
}) {
  const entryId = expandable ? numberValue(item.entryId) : null;
  const canExpand = entryId !== null;
  const title = itemTitle(item, index);
  const path = itemPath(item);
  const summary = itemSummary(item);
  const relevance = relevanceLabel(stringValue(item.relevanceLevel));
  const relevanceReason = stringValue(item.relevanceReason);
  return (
    <View style={styles.listItem}>
      <Pressable
        accessibilityRole={canExpand ? "button" : undefined}
        accessibilityLabel={
          canExpand
            ? `第 ${index + 1} 条，${title}，打开知识详情`
            : `第 ${index + 1} 项，${title}`
        }
        disabled={!canExpand}
        onPress={() => {
          if (entryId === null) return;
          onOpenEntry({
            entryId,
            title,
            projectName: stringValue(item.projectName),
            nodePath: stringValue(item.path) ?? stringValue(item.nodePath),
          });
        }}
        style={({ pressed }) => [styles.listPress, pressed && canExpand && styles.pressed]}
      >
        <View style={styles.indexBadge}>
          <Text style={styles.indexText}>{index + 1}</Text>
        </View>
        <View style={styles.listMain}>
          <Text style={styles.listItemTitle}>{title}</Text>
          {path ? (
            <Text style={styles.listPath} numberOfLines={1} ellipsizeMode="tail">
              {path}
            </Text>
          ) : null}
          {summary ? (
            <Text style={styles.listSummary} numberOfLines={1} ellipsizeMode="tail">
              {summary}
            </Text>
          ) : null}
          {relevance || relevanceReason ? (
            <Text style={styles.listRelevance}>
              {[relevance, relevanceReason].filter(Boolean).join("：")}
            </Text>
          ) : null}
          {expandable && !canExpand ? (
            <Text style={styles.listUnavailable}>缺少明确 Entry 标识，不能读取正文。</Text>
          ) : null}
        </View>
        {canExpand ? (
          <View>
            <AgentIcon name="chevron" size={16} color={theme.muted} />
          </View>
        ) : null}
      </Pressable>
    </View>
  );
}

function ListBlock({
  block,
  onOpenEntry,
}: {
  block: KnowledgeAnswerBlock;
  onOpenEntry: (target: EntryDetailTarget) => void;
}) {
  const subject = listSubject(block);
  const items = Array.isArray(block.items) ? block.items : [];
  const total = block.semantics?.totalCount;
  const returned = block.semantics?.returnedCount ?? items.length;
  return (
    <View style={styles.blockBox}>
      <View style={styles.blockHead}>
        <AgentIcon
          name={subject === "projects" || subject === "directories" ? "folder" : "book"}
          size={16}
          color={theme.confirmed}
        />
        <View style={styles.blockHeadMain}>
          <Text style={styles.blockTitle}>{listTitle(block, subject)}</Text>
          <Text style={styles.blockMeta}>
            {typeof total === "number" ? `总数 ${total}，本次返回 ${returned}` : `${returned} 项`}
          </Text>
        </View>
      </View>
      {items.length === 0 ? (
        <Text style={styles.emptyCopy}>本次没有返回可展示的列表项。</Text>
      ) : (
        items.map((item, index) => (
          <ListItem
            key={`${String(item.id ?? item.entryId ?? item.nodeId ?? index)}-${index}`}
            item={item}
            index={index}
            expandable={subject === "entries"}
            onOpenEntry={onOpenEntry}
          />
        ))
      )}
    </View>
  );
}

function StatisticBlock({ block }: { block: KnowledgeAnswerBlock }) {
  return (
    <View style={styles.blockBox}>
      <View style={styles.statHead}>
        <View style={styles.blockHeadMain}>
          <Text style={styles.blockEyebrow}>知识统计</Text>
          <Text style={styles.blockTitle}>{block.label ?? "统计结果"}</Text>
          {block.semantics?.queryObject ? (
            <Text style={styles.blockMeta}>{block.semantics.queryObject}</Text>
          ) : null}
        </View>
        {block.value !== null && block.value !== undefined ? (
          <Text style={styles.statValue}>{String(block.value)}</Text>
        ) : null}
      </View>
      {(block.buckets ?? []).map((bucket, index) => (
        <View key={`${bucket.key ?? bucket.label ?? index}-${index}`} style={styles.bucketRow}>
          <Text style={styles.bucketLabel}>{bucket.label ?? bucket.key ?? "未命名"}</Text>
          <Text style={styles.bucketCount}>{bucket.count ?? 0}</Text>
        </View>
      ))}
      {block.completeness && block.completeness !== "complete" ? (
        <Text style={styles.boundaryCopy}>统计只覆盖本次返回的有限结果。</Text>
      ) : null}
    </View>
  );
}

function AnswerBlock({
  block,
  onOpenEntry,
}: {
  block: KnowledgeAnswerBlock;
  onOpenEntry: (target: EntryDetailTarget) => void;
}) {
  if (block.kind === "text") {
    return block.text ? <Text style={styles.textBlock}>{block.text}</Text> : <UnknownBlock />;
  }
  if (block.kind === "insufficient") {
    return (
      <View style={styles.insufficient} accessibilityRole="alert">
        <AgentIcon name="alert" size={16} color={theme.risk} />
        <Text style={styles.insufficientText}>
          {block.text || "当前材料不足，无法完成本轮回答。"}
        </Text>
      </View>
    );
  }
  if (block.kind === "candidate" || block.kind === "candidate_text_only") {
    return (
      <View style={styles.candidate}>
        <View style={styles.candidateHead}>
          <AgentIcon name="edit" size={15} color={theme.ai} />
          <Text style={styles.candidateTitle}>AI 修改建议 / 候选稿 · 未应用</Text>
        </View>
        <Text style={styles.textBlock}>
          {block.text || block.content || "候选内容为空。"}
        </Text>
      </View>
    );
  }
  if (block.kind === "list") {
    return <ListBlock block={block} onOpenEntry={onOpenEntry} />;
  }
  if (block.kind === "statistic") return <StatisticBlock block={block} />;
  if (block.kind === "entry") {
    return (
      <View style={styles.blockBox}>
        <View style={styles.blockHead}>
          <AgentIcon name="book" size={16} color={theme.confirmed} />
          <View style={styles.blockHeadMain}>
            <Text style={styles.blockEyebrow}>本轮读取的知识正文</Text>
            <Text style={styles.blockTitle}>
              {block.title || block.entryTitle || "未命名知识"}
            </Text>
            <Text style={styles.blockMeta}>
              {[block.projectName, block.nodePath].filter(Boolean).join(" · ") || "归属未标注"}
            </Text>
          </View>
        </View>
        <Text style={styles.entryContent}>{block.content || block.text || "正文为空。"}</Text>
      </View>
    );
  }
  if (block.kind === "evidence") {
    return (
      <View style={styles.evidence}>
        <View style={styles.candidateHead}>
          <AgentIcon name="quote" size={15} color={theme.confirmed} />
          <Text style={styles.evidenceTitle}>本轮已核验依据</Text>
        </View>
        <Text style={styles.evidenceText}>
          {block.text || block.content || "服务端未返回可展示的依据文本。"}
        </Text>
      </View>
    );
  }
  return <UnknownBlock />;
}

function UnknownBlock() {
  return (
    <View style={styles.unknown} accessibilityRole="alert">
      <Text style={styles.unknownText}>有一项结果暂不支持展示，其余内容不受影响。</Text>
    </View>
  );
}

export function AnswerCard({
  run,
  scopeLabel,
  canContinue,
  onContinue,
  onRetry,
  onOpenEntry,
}: {
  run: KnowledgeRun;
  scopeLabel: string;
  canContinue: boolean;
  onContinue: () => void;
  onRetry: () => void;
  onOpenEntry: (target: EntryDetailTarget) => void;
}) {
  const blocks = Array.isArray(run.dialogueBlocks) ? run.dialogueBlocks : [];
  const fallbackText =
    blocks.length === 0 ? run.answer?.answer?.trim() || null : null;
  const status = dialogueStatusOf(run);
  return (
    <Card>
      <CardBody>
        <View style={styles.answerHead}>
          <View>
            <Text style={styles.blockEyebrow}>AI 即时回答</Text>
            <Text style={styles.scope}>范围：{scopeLabel}</Text>
          </View>
          <Badge
            tone={
              status === "completed"
                ? "confirmed"
                : status === "failed" || status === "unsupported"
                  ? "error"
                  : "risk"
            }
          >
            {STATUS_LABELS[status] ?? "已结束"}
          </Badge>
        </View>
        <View style={styles.blocks}>
          {blocks.map((block, index) => (
            <AnswerBlock
              key={`${block.kind}-${index}`}
              block={block}
              onOpenEntry={onOpenEntry}
            />
          ))}
          {fallbackText ? <Text style={styles.textBlock}>{fallbackText}</Text> : null}
          {!fallbackText && blocks.length === 0 ? (
            <UnknownBlock />
          ) : null}
        </View>
        <StatusNotice run={run} />
        {canContinue ? (
          <View style={styles.continueBox}>
            <Text style={styles.continueCopy}>已完成的材料已保留，可以继续未完成步骤。</Text>
            <AppButton
              label="继续"
              onPress={onContinue}
              icon={<AgentIcon name="retry" size={15} color={theme.ink} />}
            />
          </View>
        ) : null}
        {status === "failed" ? (
          <AppButton label="重新提问" onPress={onRetry} />
        ) : null}
      </CardBody>
    </Card>
  );
}

const styles = StyleSheet.create({
  answerHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 10,
  },
  scope: { marginTop: 3, color: theme.muted, fontSize: 11 },
  blocks: { marginTop: 12, gap: 10 },
  textBlock: { color: theme.ink, fontSize: 14, lineHeight: 23 },
  blockBox: {
    overflow: "hidden",
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.surface,
  },
  blockHead: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 11,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  blockHeadMain: { flex: 1, minWidth: 0 },
  blockEyebrow: { color: theme.muted, fontSize: 10, fontWeight: "700" },
  blockTitle: { color: theme.ink, fontSize: 13, lineHeight: 19, fontWeight: "700" },
  blockMeta: { marginTop: 2, color: theme.muted, fontSize: 10, lineHeight: 16 },
  listItem: { borderTopWidth: 1, borderTopColor: theme.border },
  listPress: {
    minHeight: 56,
    flexDirection: "row",
    alignItems: "center",
    gap: 9,
    paddingHorizontal: 11,
    paddingVertical: 9,
  },
  indexBadge: {
    width: 24,
    height: 24,
    borderRadius: 5,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.soft,
  },
  indexText: { color: theme.muted, fontSize: 11, fontWeight: "700" },
  listMain: { flex: 1, minWidth: 0 },
  listItemTitle: { color: theme.ink, fontSize: 13, lineHeight: 19, fontWeight: "600" },
  listPath: { marginTop: 2, color: theme.muted, fontSize: 11, lineHeight: 17 },
  listSummary: { marginTop: 2, color: theme.muted, fontSize: 12, lineHeight: 18 },
  listRelevance: { marginTop: 3, color: theme.confirmed, fontSize: 11, lineHeight: 17 },
  listUnavailable: { marginTop: 3, color: theme.risk, fontSize: 10, lineHeight: 16 },
  entryContent: { padding: 11, color: theme.ink, fontSize: 13, lineHeight: 22 },
  statHead: { flexDirection: "row", gap: 12, padding: 11 },
  statValue: { color: theme.confirmed, fontSize: 23, fontWeight: "700" },
  bucketRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10,
    paddingHorizontal: 11,
    paddingVertical: 7,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  bucketLabel: { flex: 1, color: theme.ink, fontSize: 12 },
  bucketCount: { color: theme.confirmed, fontSize: 12, fontWeight: "700" },
  boundaryCopy: { padding: 10, color: theme.risk, fontSize: 10, lineHeight: 16 },
  insufficient: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    padding: 11,
    borderWidth: 1,
    borderColor: "#EFD7A8",
    borderRadius: 8,
    backgroundColor: theme.riskSoft,
  },
  insufficientText: { flex: 1, color: theme.risk, fontSize: 12, lineHeight: 20 },
  candidate: {
    gap: 7,
    padding: 11,
    borderWidth: 1,
    borderColor: "#DACCDE",
    borderRadius: 8,
    backgroundColor: theme.aiSoft,
  },
  candidateHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  candidateTitle: { color: theme.ai, fontSize: 11, fontWeight: "700" },
  evidence: {
    gap: 7,
    padding: 11,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.confirmedSoft,
  },
  evidenceTitle: { color: theme.confirmed, fontSize: 11, fontWeight: "700" },
  evidenceText: { color: theme.ink, fontSize: 12, lineHeight: 20 },
  unknown: {
    padding: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
    backgroundColor: theme.soft,
  },
  unknownText: { color: theme.muted, fontSize: 11, lineHeight: 18 },
  emptyCopy: { padding: 11, color: theme.muted, fontSize: 11 },
  notice: {
    marginTop: 11,
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    padding: 10,
    borderRadius: 8,
    backgroundColor: theme.riskSoft,
  },
  noticeError: { backgroundColor: theme.errorSoft },
  noticeMain: { flex: 1 },
  noticeTitle: { color: theme.risk, fontSize: 12, fontWeight: "700" },
  noticeErrorText: { color: theme.error },
  noticeCopy: { marginTop: 2, color: theme.muted, fontSize: 11, lineHeight: 18 },
  continueBox: { marginTop: 11, gap: 8 },
  continueCopy: { color: theme.muted, fontSize: 11, lineHeight: 18 },
  pressed: { opacity: 0.82 },
});
