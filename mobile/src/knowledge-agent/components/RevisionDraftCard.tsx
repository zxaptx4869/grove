import { Pressable, StyleSheet, Text, View } from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import {
  AppButton,
  Badge,
  Card,
  CardBody,
  Eyebrow,
} from "@/src/knowledge-agent/components/ui";
import type {
  KnowledgeEntryRevisionDraft,
  KnowledgeRun,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

function changedFieldLabel(draft: KnowledgeEntryRevisionDraft): string {
  const fields = draft.changedFields.map((item) => item.label);
  return fields.length > 0 ? fields.join("、") : "暂无字段变化";
}

/** 修订草稿生成中：只展示可验证阶段，不展示隐藏推理。 */
export function RevisionProcessCard({
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
              修订这条知识
            </Eyebrow>
            <Text style={styles.title}>
              {cancelled ? "正在取消修订…" : "正在生成修订草稿"}
            </Text>
          </View>
          <Badge tone={cancelled ? "neutral" : "ai"}>
            {cancelled ? "正在取消" : "生成中"}
          </Badge>
        </View>
        <Text style={styles.processCopy}>
          正在核对来源证据并生成可编辑草稿；确认前不会修改正式知识。
        </Text>
        {!cancelled && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="取消修订"
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

/** 已生成的可编辑修订草稿：AI 建议语义，区别于正式 Entry 与即时回答。 */
export function RevisionDraftCard({
  draft,
  confirming,
  onEdit,
  onConfirm,
  onCancel,
}: {
  draft: KnowledgeEntryRevisionDraft;
  confirming: boolean;
  onEdit: () => void;
  onConfirm: () => void;
  onCancel: () => void;
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
            <Text style={styles.title}>{draft.title ?? "未命名修订草稿"}</Text>
          </View>
          <Badge tone="ai">AI 建议 · 待确认</Badge>
        </View>
        <View style={styles.metaRow}>
          <AgentIcon name="book" size={14} color={theme.muted} />
          <Text style={styles.metaText} numberOfLines={2}>
            目标：{draft.title ?? "未命名修订草稿"}
          </Text>
        </View>
        <View style={styles.metaRow}>
          <AgentIcon name="folder" size={14} color={theme.muted} />
          <Text style={styles.metaText}>
            {draft.targetProjectName ?? "未知项目"}
            {draft.targetEntryId ? " · 单条正式知识" : ""}
          </Text>
        </View>
        <View style={styles.metaRow}>
          <AgentIcon name="edit" size={14} color={theme.muted} />
          <Text style={styles.metaText}>
            变化字段：
            {draft.changedFields.length > 0
              ? `${draft.changedFields.length} 项（${changedFieldLabel(draft)}）`
              : "暂未计算"}
          </Text>
        </View>
        <View style={styles.metaRow}>
          <AgentIcon name="quote" size={14} color={theme.muted} />
          <Text style={styles.metaText}>
            来源：{sourceCount > 0 ? `${sourceCount} 条核验证据` : "暂无来源"}
          </Text>
        </View>
        {draft.generationDegraded && (
          <View style={styles.degradedBox}>
            <Text style={styles.degradedText}>
              修订生成已降级：模型暂不可用，草稿未生成，请重新生成后确认。
            </Text>
          </View>
        )}
        <View style={styles.actions}>
          <AppButton label="编辑并检查" variant="primary" onPress={onEdit} />
          <AppButton
            label="确认修改"
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

/** 修订草稿失败/已取消：保留错误与重试入口，不创建成功回执。 */
export function RevisionDraftFailedCard({
  draft,
  onRetry,
}: {
  draft: KnowledgeEntryRevisionDraft;
  onRetry: () => void;
}) {
  if (draft.status === "cancelled") {
    return (
      <Card>
        <CardBody>
          <View style={styles.head}>
            <View style={styles.headMain}>
              <Eyebrow icon={<AgentIcon name="close" size={14} color={theme.muted} />}>
                已取消修订
              </Eyebrow>
              <Text style={styles.title}>这次修订已取消</Text>
            </View>
            <Badge tone="neutral">已取消</Badge>
          </View>
          <Text style={styles.processCopy}>
            没有修改正式知识；如需修订，请在对应引用上重新发起。
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
              修订草稿生成失败
            </Eyebrow>
            <Text style={styles.title}>没有生成可编辑草稿</Text>
          </View>
          <Badge tone="error">失败</Badge>
        </View>
        <Text style={styles.errorCopy}>
          {draft.error ?? "修订草稿生成未完成，请重试。"}
        </Text>
        <View style={styles.actions}>
          <AppButton label="重新修订" variant="primary" onPress={onRetry} />
        </View>
      </CardBody>
    </Card>
  );
}

/** applied 回执：正式知识已更新，可查看差异/撤销（并发安全边界可见）。 */
export function RevisionReceiptCard({
  draft,
  undoing,
  undoError,
  onViewDiff,
  onUndo,
  onRetryUndo,
}: {
  draft: KnowledgeEntryRevisionDraft;
  undoing: boolean;
  undoError: string | null;
  onViewDiff: () => void;
  onUndo: () => void;
  onRetryUndo: () => void;
}) {
  const undone = draft.status === "undone";
  const execution = draft.execution;
  const addedSources = execution?.addedEvidenceCount ?? 0;
  return (
    <Card style={undone ? styles.receiptCardUndone : styles.receiptCard}>
      <CardBody>
        <View style={styles.receiptTop}>
          <View
            style={[
              styles.receiptIcon,
              undone && styles.receiptIconUndone,
            ]}
          >
            <AgentIcon
              name={undone ? "retry" : "circleCheck"}
              size={20}
              color={undone ? theme.muted : theme.confirmed}
            />
          </View>
          <View style={styles.headMain}>
            <Eyebrow
              icon={
                <AgentIcon
                  name={undone ? "check" : "check"}
                  size={14}
                  color={undone ? theme.muted : theme.confirmed}
                />
              }
            >
              {undone ? "操作已撤销 · 审计记录保留" : "正式知识已更新"}
            </Eyebrow>
            <Text style={styles.title}>
              {undone ? "已恢复到修订前状态" : draft.title ?? "未命名知识"}
            </Text>
            {!undone && (
              <Text style={styles.receiptCaption}>
                更新 1 条正式知识 · 尚未发生后续修改时可撤销
              </Text>
            )}
          </View>
        </View>
        <View style={styles.receiptList}>
          <View style={styles.receiptRow}>
            <Text style={styles.receiptLabel}>版本</Text>
            <Text style={styles.receiptValue}>
              {undone
                ? `已恢复版本 ${execution?.beforeVersionNumber ?? "—"}`
                : `已更新至版本 ${execution?.afterVersionNumber ?? "—"}`}
            </Text>
          </View>
          <View style={styles.receiptRow}>
            <Text style={styles.receiptLabel}>来源证据</Text>
            <Text style={styles.receiptValue}>
              {undone
                ? "仅移除本次新增"
                : addedSources > 0
                  ? `新增 ${addedSources} 条，既有全部保留`
                  : "既有全部保留"}
            </Text>
          </View>
          {undone && (
            <View style={styles.receiptRow}>
              <Text style={styles.receiptLabel}>操作记录</Text>
              <Text style={styles.receiptValue}>保留撤销审计</Text>
            </View>
          )}
        </View>
        {undoError !== null && (
          <View style={styles.errorBox}>
            <Text style={styles.errorCopy}>{undoError}</Text>
            <AppButton label="重试撤销" variant="primary" onPress={onRetryUndo} />
          </View>
        )}
        <View style={styles.actions}>
          {undone ? (
            <AppButton
              label="查看恢复结果"
              variant="primary"
              onPress={onViewDiff}
            />
          ) : (
            <>
              <AppButton label="查看差异" variant="default" onPress={onViewDiff} />
              <AppButton
                label={undoing ? "撤销中…" : "撤销"}
                variant="danger"
                disabled={undoing}
                onPress={onUndo}
              />
            </>
          )}
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
  errorBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 7,
    backgroundColor: theme.errorSoft,
    gap: 6,
  },
  receiptCard: { borderColor: "#BDDBD2" },
  receiptCardUndone: { borderColor: theme.border },
  receiptTop: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  receiptIcon: {
    width: 34,
    height: 34,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 8,
    backgroundColor: theme.confirmedSoft,
  },
  receiptIconUndone: {
    backgroundColor: theme.soft,
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
});
