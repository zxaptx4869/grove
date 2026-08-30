import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import { AppButton, Badge, Card, CardBody, Eyebrow } from "@/src/knowledge-agent/components/ui";
import { draftMainTypeLabel } from "@/src/knowledge-agent/draftTypes";
import type {
  KnowledgeCandidateDraft,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

/** 草稿生成中：只展示可验证阶段，不展示隐藏推理。 */
export function DraftProcessCard({
  run,
  cancelling,
  onCancel,
}: {
  run: KnowledgeRun;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const cancelled = run.cancelRequested || cancelling;
  return (
    <Card accent="ai">
      <CardBody>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="edit" size={14} color={theme.ai} />}>
              整理成知识
            </Eyebrow>
            <Text style={styles.title}>
              {cancelled ? "正在取消整理…" : "正在生成候选草稿"}
            </Text>
          </View>
          <Badge tone={cancelled ? "neutral" : "ai"}>
            {cancelled ? "正在取消" : "生成中"}
          </Badge>
        </View>
        <Text style={styles.processCopy}>
          正在核对来源证据并生成可编辑草稿，完成后仍需你确认。
        </Text>
        {!cancelled && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="取消整理"
            onPress={onCancel}
            style={({ pressed }) => [styles.cancelButton, pressed && styles.pressed]}
          >
            <Text style={styles.cancelText}>取消</Text>
          </Pressable>
        )}
      </CardBody>
    </Card>
  );
}

/** 已生成的可编辑草稿：AI 建议语义，区别于即时回答与正式知识。 */
export function DraftCard({
  draft,
  onEdit,
  onConfirm,
  onCancel,
  confirming,
}: {
  draft: KnowledgeCandidateDraft;
  onEdit: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  confirming: boolean;
}) {
  const sourceCount = draft.evidenceSummaries.length;
  return (
    <Card accent="ai">
      <CardBody>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="edit" size={14} color={theme.ai} />}>
              可编辑知识草稿
            </Eyebrow>
            <Text style={styles.title}>{draft.title ?? "未命名草稿"}</Text>
          </View>
          <Badge tone="ai">AI 草稿 · 未创建候选</Badge>
        </View>
        {draft.content !== null && draft.content.trim() !== "" && (
          <Text style={styles.content}>{draft.content}</Text>
        )}
        <View style={styles.metaRow}>
          <AgentIcon name="folder" size={14} color={theme.muted} />
          <Text style={styles.metaText}>
            目标项目：{draft.targetProjectName ?? "未知项目"}
          </Text>
        </View>
        <View style={styles.metaRow}>
          <AgentIcon name="quote" size={14} color={theme.muted} />
          <Text style={styles.metaText}>
            来源摘要：{sourceCount > 0 ? `${sourceCount} 条核验证据` : "暂无来源"}
          </Text>
        </View>
        {draft.mainType !== null && (
          <View style={styles.metaRow}>
            <AgentIcon name="book" size={14} color={theme.muted} />
            <Text style={styles.metaText}>
              类型建议：{draftMainTypeLabel(draft.mainType)}
            </Text>
          </View>
        )}
        {draft.generationDegraded && (
          <View style={styles.degradedBox}>
            <Text style={styles.degradedText}>
              草稿生成已降级：模型暂不可用，草稿由原回答生成，仍只采用核验证据，请检查后确认。
            </Text>
          </View>
        )}
        <View style={styles.actions}>
          <AppButton
            label="编辑并检查"
            variant="primary"
            onPress={onEdit}
          />
          <AppButton
            label="创建待确认知识"
            variant="ai"
            disabled={confirming}
            onPress={onConfirm}
          />
          <AppButton
            label="取消"
            variant="ghost"
            disabled={confirming}
            onPress={onCancel}
          />
        </View>
      </CardBody>
    </Card>
  );
}

/** 确认回执：Candidate 仍待确认、尚未写入正式知识。 */
export function DraftReceiptCard({
  draft,
}: {
  draft: KnowledgeCandidateDraft;
}) {
  const sourceCount = draft.evidenceSummaries.length;
  const routingPending =
    draft.status === "confirmed" && draft.confirmedCandidateId !== null;
  return (
    <Card style={styles.receiptCard}>
      <CardBody>
        <View style={styles.receiptTop}>
          <View style={styles.receiptIcon}>
            <AgentIcon name="circleCheck" size={20} color={theme.confirmed} />
          </View>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="check" size={14} color={theme.confirmed} />}>
              已创建待确认知识
            </Eyebrow>
            <Text style={styles.title}>{draft.title ?? "未命名草稿"}</Text>
            <Text style={styles.receiptCaption}>
              尚未写入正式知识 · 创建时间{" "}
              {draft.updatedAt ? new Date(draft.updatedAt).toLocaleString() : "—"}
            </Text>
          </View>
        </View>
        <View style={styles.receiptList}>
          <View style={styles.receiptRow}>
            <Text style={styles.receiptLabel}>目标项目</Text>
            <Text style={styles.receiptValue}>
              {draft.targetProjectName ?? "未知项目"}
            </Text>
          </View>
          <View style={styles.receiptRow}>
            <Text style={styles.receiptLabel}>Candidate</Text>
            <Text style={styles.receiptValue}>
              待确认（#{draft.confirmedCandidateId ?? "—"}）
            </Text>
          </View>
          <View style={styles.receiptRow}>
            <Text style={styles.receiptLabel}>来源证据</Text>
            <Text style={styles.receiptValue}>
              {sourceCount > 0 ? `${sourceCount} 条，全部保留` : "—"}
            </Text>
          </View>
        </View>
        {routingPending && (
          <Text style={styles.receiptNote}>
            目录与关系建议仍在待确认流程中处理，尚未写入正式知识。
          </Text>
        )}
      </CardBody>
    </Card>
  );
}

/** 草稿失败/已取消：保留错误与重试入口，不创建成功回执。 */
export function DraftFailedCard({
  draft,
  onRetry,
}: {
  draft: KnowledgeCandidateDraft;
  onRetry: () => void;
}) {
  if (draft.status === "cancelled") {
    return (
      <Card>
        <CardBody>
          <View style={styles.head}>
            <View style={styles.headMain}>
              <Eyebrow icon={<AgentIcon name="close" size={14} color={theme.muted} />}>
                已取消整理
              </Eyebrow>
              <Text style={styles.title}>这次整理已取消</Text>
            </View>
            <Badge tone="neutral">已取消</Badge>
          </View>
          <Text style={styles.processCopy}>
            没有创建候选草稿；如需整理，请在对应回答上重新发起。
          </Text>
        </CardBody>
      </Card>
    );
  }
  return (
    <Card accent="risk">
      <CardBody>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="alert" size={14} color={theme.error} />}>
              草稿生成失败
            </Eyebrow>
            <Text style={styles.title}>没有生成可编辑草稿</Text>
          </View>
          <Badge tone="error">失败</Badge>
        </View>
        <Text style={styles.errorCopy}>
          {draft.error ?? "草稿生成未完成，请重试。"}
        </Text>
        <View style={styles.actions}>
          <AppButton label="重新整理" variant="primary" onPress={onRetry} />
        </View>
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
  content: {
    marginTop: 10,
    fontSize: 13,
    lineHeight: 21,
    color: theme.ink,
  },
  processCopy: {
    marginTop: 10,
    fontSize: 12,
    lineHeight: 20,
    color: theme.muted,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 8,
  },
  metaText: { color: theme.muted, fontSize: 11, lineHeight: 17, flexShrink: 1 },
  degradedBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 7,
    backgroundColor: theme.riskSoft,
  },
  degradedText: { color: "#76501C", fontSize: 12, lineHeight: 19 },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 12,
    flexWrap: "wrap",
  },
  cancelButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 12,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 8,
  },
  cancelText: { fontSize: 13, fontWeight: "600", color: theme.ink },
  pressed: { opacity: 0.9 },
  errorCopy: {
    marginTop: 10,
    color: theme.error,
    fontSize: 12,
    lineHeight: 19,
  },
  receiptCard: { borderColor: "#BDDBD2" },
  receiptTop: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  receiptIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.confirmedSoft,
  },
  receiptCaption: {
    marginTop: 4,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  receiptList: {
    marginTop: 12,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  receiptRow: {
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.border,
  },
  receiptLabel: { fontSize: 12, color: theme.ink },
  receiptValue: {
    fontSize: 12,
    color: theme.muted,
    textAlign: "right",
    flexShrink: 1,
  },
  receiptNote: {
    marginTop: 10,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
});
