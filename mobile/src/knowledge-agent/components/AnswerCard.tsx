import { useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { AgentIcon } from "@/src/knowledge-agent/components/AgentIcon";
import {
  AppButton,
  Badge,
  Card,
  CardBody,
  Eyebrow,
  type BadgeTone,
} from "@/src/knowledge-agent/components/ui";
import {
  cleanAnswerText,
  draftActionEligibility,
  investigationSummaryLine,
  presentAnswer,
  stopReasonLabel,
} from "@/src/knowledge-agent/adapters/answer";
import { presentFallback } from "@/src/knowledge-agent/adapters/fallback";
import type {
  KnowledgeConflict,
  KnowledgeRun,
  KnowledgeRunCitation,
} from "@/src/knowledge-agent/types";
import { theme } from "@/src/theme";

function ScopeStamp({ label }: { label: string }) {
  return (
    <View style={styles.scopeStamp}>
      <AgentIcon name="folder" size={14} color={theme.muted} />
      <Text style={styles.scopeStampText}>检索范围：{label}</Text>
    </View>
  );
}

function CitationStrip({
  citations,
  workspaceScope,
  onCitationPress,
}: {
  citations: KnowledgeRunCitation[];
  workspaceScope: boolean;
  onCitationPress: (citation: KnowledgeRunCitation) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <View style={styles.sourceStrip}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.sourceStripContent}
      >
        {citations.map((citation) => (
          <Pressable
            key={citation.evidenceId}
            accessibilityRole="button"
            accessibilityLabel={`查看引用：${citation.entryTitle}`}
            onPress={() => onCitationPress(citation)}
            style={({ pressed }) => [
              styles.sourceChip,
              pressed && styles.sourceChipPressed,
            ]}
          >
            <AgentIcon name="quote" size={14} color={theme.muted} />
            <Text style={styles.sourceChipText} numberOfLines={1}>
              {workspaceScope && citation.projectName
                ? `${citation.projectName} · ${citation.entryTitle}`
                : citation.entryTitle}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
    </View>
  );
}

export function ConflictCard({
  conflict,
  onCitationPress,
}: {
  conflict: KnowledgeConflict;
  onCitationPress: (citation: KnowledgeRunCitation) => void;
}) {
  return (
    <Card accent="risk">
      <CardBody>
        <View style={styles.conflictHead}>
          <View style={styles.headMain}>
            <Eyebrow icon={<AgentIcon name="alert" size={14} color={theme.risk} />}>
              冲突观点
            </Eyebrow>
            <Text style={styles.conflictTitle}>{conflict.summary}</Text>
          </View>
          <Badge tone="risk">需要判断</Badge>
        </View>
        <ConflictSide
          label="观点 A"
          entryTitle={conflict.entryTitleA}
          citation={conflict.citationA}
          onCitationPress={onCitationPress}
        />
        <ConflictSide
          label="观点 B"
          entryTitle={conflict.entryTitleB}
          citation={conflict.citationB}
          onCitationPress={onCitationPress}
        />
      </CardBody>
    </Card>
  );
}

function ConflictSide({
  label,
  entryTitle,
  citation,
  onCitationPress,
}: {
  label: string;
  entryTitle: string;
  citation: KnowledgeRunCitation | null;
  onCitationPress: (citation: KnowledgeRunCitation) => void;
}) {
  return (
    <View style={styles.conflictSide}>
      <Text style={styles.conflictSideLabel}>
        {label}：{entryTitle}
      </Text>
      {citation ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`查看${label}的证据原文`}
          onPress={() => onCitationPress(citation)}
          style={({ pressed }) => [
            styles.conflictEvidenceButton,
            pressed && styles.sourceChipPressed,
          ]}
        >
          <AgentIcon name="file" size={14} color={theme.confirmed} />
          <Text style={styles.conflictEvidenceText}>
            {citation.sourceTitle} · 查看原文
          </Text>
        </Pressable>
      ) : (
        <Text style={styles.conflictMissing}>
          历史回答未保存双边完整证据，仅保留标题摘要。
        </Text>
      )}
    </View>
  );
}

function InvestigationSummary({
  run,
}: {
  run: KnowledgeRun;
}) {
  const summary = run.investigationSummary;
  const [expanded, setExpanded] = useState(false);
  if (!summary) return null;
  const stopReason = stopReasonLabel(summary.stopReason);
  return (
    <View style={styles.investigation}>
      <View style={styles.investigationRow}>
        <Text style={styles.investigationLine}>
          {investigationSummaryLine(summary)}
        </Text>
        {stopReason && (
          <Text style={styles.investigationStop}>停止原因：{stopReason}</Text>
        )}
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        accessibilityLabel={expanded ? "收起调查摘要" : "展开调查摘要"}
        onPress={() => setExpanded((value) => !value)}
        style={styles.investigationToggle}
      >
        <Text style={styles.investigationToggleText}>
          {expanded ? "收起覆盖、缺口与冲突" : "查看覆盖、缺口与冲突"}
        </Text>
      </Pressable>
      {expanded && (
        <View style={styles.investigationDetails}>
          <InvestigationGroup label="覆盖" items={summary.coverage} />
          <InvestigationGroup label="未解决缺口" items={summary.gaps} />
          <InvestigationGroup label="冲突线索" items={summary.conflicts} />
        </View>
      )}
    </View>
  );
}

function InvestigationGroup({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <View style={styles.investigationGroup}>
      <Text style={styles.investigationGroupLabel}>{label}</Text>
      {items.map((item, index) => (
        <Text key={`${label}-${index}`} style={styles.investigationItem}>
          · {item}
        </Text>
      ))}
    </View>
  );
}

export function AnswerCard({
  run,
  scopeLabel,
  onCitationPress,
  onRetry,
  onOrganize,
  onRefineQuestion,
}: {
  run: KnowledgeRun;
  scopeLabel: string;
  onCitationPress: (citation: KnowledgeRunCitation) => void;
  onRetry: () => void;
  onOrganize: (run: KnowledgeRun) => void;
  onRefineQuestion?: (run: KnowledgeRun) => void;
}) {
  const answer = run.answer;
  const presentation = presentAnswer(answer, run.status);
  const fallback = presentFallback(run.fallbackSummary);
  const tone: BadgeTone =
    presentation.tone === "positive" ? "confirmed" : presentation.tone;
  const workspaceScope = run.scopeType === "workspace";
  const citations = answer?.citations ?? [];
  // partial 的「再问」不应原样重发同一问题：改为把原问题填回输入框，
  // 由用户修改措辞或切换模式后再发送（失败/降级仍支持一键重试）。
  const partialRefine = presentation.status === "partial";
  const canRetry =
    presentation.status === "failed" || fallback.hasFallback;
  const projectCounts = new Map<string, number>();
  for (const citation of citations) {
    if (!citation.projectName) continue;
    projectCounts.set(
      citation.projectName,
      (projectCounts.get(citation.projectName) ?? 0) + 1,
    );
  }
  const organize = draftActionEligibility(run);

  return (
    <>
      {presentation.status !== "cancelled" && (
        <Card
          accent={presentation.status === "insufficient" ? "risk" : undefined}
          background={
            presentation.status === "insufficient" ? theme.riskSoft : undefined
          }
        >
          <CardBody>
            <View style={styles.head}>
              <View style={styles.headMain}>
                <Eyebrow
                  icon={
                    <AgentIcon
                      name={
                        presentation.status === "completed" ? "book" : "alert"
                      }
                      size={14}
                      color={
                        presentation.status === "completed"
                          ? theme.confirmed
                          : theme.risk
                      }
                    />
                  }
                >
                  {presentation.headline}
                </Eyebrow>
                <Text style={styles.answerTitle}>
                  {presentation.status === "clarification"
                    ? "需要你补充信息"
                    : presentation.status === "insufficient"
                      ? "当前知识不足以直接回答"
                      : presentation.status === "failed"
                        ? "这次回答没有完成"
                        : "综合回答"}
                </Text>
              </View>
              <Badge tone={tone}>{presentation.headline}</Badge>
            </View>
            {presentation.note !== null && (
              <Text
                style={[
                  styles.answerIntro,
                  presentation.status === "insufficient" && styles.insufficientText,
                ]}
              >
                {presentation.note}
              </Text>
            )}
            {answer && answer.answer.trim() !== "" && (
              <Text style={styles.answerBody}>{cleanAnswerText(answer.answer)}</Text>
            )}
            {fallback.hasFallback && (
              <View style={styles.fallbackBox}>
                {fallback.lines.map((line) => (
                  <Text key={line} style={styles.fallbackText}>
                    {line}
                  </Text>
                ))}
              </View>
            )}
            <InvestigationSummary run={run} />
            {workspaceScope &&
              projectCounts.size > 0 &&
              [...projectCounts.entries()].map(([projectName, count]) => (
                <View key={projectName} style={styles.projectHit}>
                  <Text style={styles.projectHitTitle}>
                    命中项目：{projectName}
                  </Text>
                  <Text style={styles.projectHitCopy}>{count} 条引用</Text>
                </View>
              ))}
            <CitationStrip
              citations={citations}
              workspaceScope={workspaceScope}
              onCitationPress={onCitationPress}
            />
            <ScopeStamp label={scopeLabel} />
            {organize.eligible && (
              <View style={styles.organizeArea}>
                {organize.note !== null && (
                  <Text style={styles.organizeNote}>{organize.note}</Text>
                )}
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="整理成知识"
                  onPress={() => onOrganize(run)}
                  style={({ pressed }) => [
                    styles.organizeButton,
                    pressed && styles.organizeButtonPressed,
                  ]}
                >
                  <Text style={styles.organizeText}>整理成知识</Text>
                  <AgentIcon name="edit" size={16} color={theme.ai} />
                </Pressable>
              </View>
            )}
            {partialRefine && onRefineQuestion !== undefined && (
              <View style={styles.inlineActions}>
                <AppButton
                  label="修改问题再问"
                  variant="default"
                  icon={<AgentIcon name="edit" size={16} color={theme.ink} />}
                  onPress={() => onRefineQuestion(run)}
                />
              </View>
            )}
            {canRetry && !partialRefine && (
              <View style={styles.inlineActions}>
                <AppButton
                  label="重新提问"
                  variant="primary"
                  icon={<AgentIcon name="retry" size={16} color="#FFFFFF" />}
                  onPress={onRetry}
                />
              </View>
            )}
          </CardBody>
        </Card>
      )}
      {presentation.status === "cancelled" && (
        <Card>
          <CardBody>
            <View style={styles.head}>
              <View style={styles.headMain}>
                <Eyebrow icon={<AgentIcon name="alert" size={14} color={theme.muted} />}>
                  已取消
                </Eyebrow>
                <Text style={styles.answerTitle}>这次回答已取消</Text>
              </View>
              <Badge tone="neutral">已取消</Badge>
            </View>
            <Text style={styles.answerIntro}>
              没有生成正常回答，可以重新提问。
            </Text>
            <View style={styles.inlineActions}>
              <AppButton
                label="重新提问"
                variant="primary"
                icon={<AgentIcon name="retry" size={16} color="#FFFFFF" />}
                onPress={onRetry}
              />
            </View>
          </CardBody>
        </Card>
      )}
      {answer?.conflicts.map((conflict) => (
        <ConflictCard
          key={`${conflict.evidenceIdA}-${conflict.evidenceIdB}`}
          conflict={conflict}
          onCitationPress={onCitationPress}
        />
      ))}
    </>
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
  answerTitle: {
    marginTop: 4,
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: theme.ink,
  },
  answerIntro: {
    marginTop: 10,
    fontSize: 14,
    lineHeight: 23,
    color: theme.ink,
  },
  answerBody: {
    marginTop: 10,
    fontSize: 14,
    lineHeight: 23,
    color: theme.ink,
  },
  insufficientText: { color: "#76501C" },
  fallbackBox: {
    marginTop: 10,
    padding: 10,
    borderRadius: 7,
    backgroundColor: theme.riskSoft,
  },
  fallbackText: { color: "#76501C", fontSize: 12, lineHeight: 20 },
  projectHit: {
    marginTop: 10,
    padding: 9,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 7,
    backgroundColor: theme.bg,
  },
  projectHitTitle: { fontSize: 12, fontWeight: "600", color: theme.ink },
  projectHitCopy: {
    marginTop: 3,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  sourceStrip: {
    marginTop: 14,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  sourceStripContent: { gap: 6, paddingRight: 6 },
  sourceChip: {
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 10,
    borderWidth: 1,
    borderColor: theme.border,
    borderRadius: 7,
    backgroundColor: theme.surface,
    maxWidth: 230,
  },
  sourceChipPressed: { opacity: 0.85, borderColor: theme.green },
  sourceChipText: {
    color: theme.muted,
    fontSize: 11,
    fontWeight: "600",
    flexShrink: 1,
  },
  scopeStamp: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  scopeStampText: { color: theme.muted, fontSize: 10, lineHeight: 16 },
  organizeArea: { marginTop: 12 },
  organizeNote: {
    marginBottom: 8,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 17,
  },
  organizeButton: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    borderWidth: 1,
    borderColor: "#DACCDE",
    borderRadius: 9,
    backgroundColor: theme.aiSoft,
  },
  organizeButtonPressed: { opacity: 0.9 },
  organizeText: { color: theme.ai, fontSize: 13, fontWeight: "600" },
  inlineActions: { flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" },
  conflictHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 10,
  },
  conflictTitle: {
    marginTop: 4,
    fontSize: 16,
    lineHeight: 23,
    fontWeight: "700",
    color: theme.ink,
  },
  conflictSide: {
    marginTop: 10,
    padding: 9,
    borderWidth: 1,
    borderColor: "#F0DFBA",
    borderRadius: 7,
    backgroundColor: "#FFFAF0",
  },
  conflictSideLabel: { fontSize: 12, lineHeight: 18, fontWeight: "700", color: theme.ink },
  conflictEvidenceButton: {
    minHeight: 40,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 6,
  },
  conflictEvidenceText: {
    color: theme.confirmed,
    fontSize: 12,
    fontWeight: "600",
    flexShrink: 1,
  },
  conflictMissing: {
    marginTop: 6,
    color: theme.muted,
    fontSize: 11,
    lineHeight: 18,
  },
  investigation: {
    marginTop: 12,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: theme.border,
  },
  investigationRow: { gap: 4 },
  investigationLine: { fontSize: 11, lineHeight: 17, color: theme.muted },
  investigationStop: { fontSize: 11, lineHeight: 17, color: theme.risk },
  investigationToggle: {
    minHeight: 44,
    justifyContent: "center",
    marginTop: 4,
  },
  investigationToggleText: {
    color: theme.green,
    fontSize: 12,
    fontWeight: "600",
  },
  investigationDetails: { gap: 8, marginTop: 4 },
  investigationGroup: { gap: 2 },
  investigationGroupLabel: {
    fontSize: 10,
    fontWeight: "700",
    color: theme.muted,
    letterSpacing: 0.2,
  },
  investigationItem: { fontSize: 11, lineHeight: 18, color: theme.muted },
});
