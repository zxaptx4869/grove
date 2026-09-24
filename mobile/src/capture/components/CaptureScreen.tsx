/** 收集栏目：入口页 / 采集页 / 权限页互斥，提交以全屏覆盖层呈现（对齐原型 setPage 与 #submitOverlay）。 */

import { useQuery } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { Platform, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { getProjects } from "@/src/api";
import { useAuth } from "@/src/auth";
import {
  createCaptureResults,
  createCaptureSubmitUnits,
  type CaptureKind,
  type CaptureResult,
  type CaptureSubmitUnit,
  type UploadFile,
} from "@/src/capture/batch";
import { readClipboardText } from "@/src/capture/clipboard";
import { AlbumChoiceSheet } from "@/src/capture/components/AlbumChoiceSheet";
import { CaptureForm, type CaptureDraft } from "@/src/capture/components/CaptureForm";
import { CaptureHeader } from "@/src/capture/components/CaptureHeader";
import { EntryRow } from "@/src/capture/components/EntryRow";
import { PermissionPage, permissionTitle } from "@/src/capture/components/PermissionPage";
import { ProjectSheet } from "@/src/capture/components/ProjectSheet";
import { SubmitOverlay, type CaptureSession } from "@/src/capture/components/SubmitOverlay";
import { newBatchId } from "@/src/capture/ids";
import { draftImages, prepareImage, type PickedAsset, type PickedImage } from "@/src/capture/image";
import {
  capturePhoto,
  ensurePermission,
  openAppSettings,
  pickImages,
  type PermissionKind,
} from "@/src/capture/picker";
import { submitCaptureUnits, toCaptureMessage } from "@/src/capture/submit";
import { triggerSourceProcessing, uploadSource } from "@/src/capture/upload";
import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";
import { AppButton } from "@/src/knowledge-agent/components/ui";
import { theme } from "@/src/theme";

/** 三个互斥页面，对应原型 data-screen。 */
type CapturePage = "entry" | "form" | "permission";

/** 采集页标题：与原型 FORM_TITLES 一致。 */
const FORM_TITLE: Record<CaptureKind, string> = {
  camera: "拍照采集",
  "album-separate": "图片采集",
  "album-merged": "图片采集",
  text: "文字采集",
};

const READY_HINT = "提交后可在「收集」列表里查看处理状态";

/** 本地压缩失败：没有服务端文案，用固定说明代替原生错误串。 */
const IMAGE_PREPARE_ERROR = "图片处理失败，请重新选择。";

type SessionMeta = { kind: CaptureKind; note: string; projectId: number | null };

function emptyDraft(kind: CaptureKind, images: PickedImage[]): CaptureDraft {
  return { kind, images, text: "", note: "", projectId: null, fromCamera: kind === "camera" };
}

/** 与原型 submitDisabled 一致：文字必须有内容，图片至少 1 张。 */
function submitDisabled(draft: CaptureDraft): boolean {
  return draft.kind === "text" ? draft.text.trim().length === 0 : draft.images.length === 0;
}

/** 与原型 formHint 一致。 */
function footerHint(draft: CaptureDraft): string {
  if (draft.kind === "text" && !draft.text.trim()) return "先填入文字，再提交";
  if (draft.kind !== "text" && draft.images.length === 0) return "至少保留 1 张图片";
  return READY_HINT;
}

/** 单张图片的压缩进度回调：total 为本批次待压缩张数，current 从 1 开始。 */
type PrepareHooks = {
  onPrepareStart: (total: number) => void;
  onPrepareStep: (current: number, total: number) => void;
  onUpdate: (key: string, patch: Partial<CaptureResult>) => void;
};

function countUnprepared(units: CaptureSubmitUnit[]): number {
  return units.reduce(
    (sum, unit) => sum + unit.files.filter((file) => !file.prepared).length,
    0,
  );
}

/**
 * 上传前的本地压缩：把选择器给的原图逐张转成 jpg。
 * 单张失败只标记该条，其余条目继续；返回压缩后的单元与可直接上传的子集。
 */
async function compressUnits(
  units: CaptureSubmitUnit[],
  hooks: PrepareHooks,
): Promise<{ units: CaptureSubmitUnit[]; ready: CaptureSubmitUnit[] }> {
  const total = countUnprepared(units);
  if (total === 0) return { units, ready: units };
  hooks.onPrepareStart(total);
  const now = Date.now();
  let done = 0;
  const compressed: CaptureSubmitUnit[] = [];
  const ready: CaptureSubmitUnit[] = [];
  for (const unit of units) {
    if (!unit.files.some((file) => !file.prepared)) {
      compressed.push(unit);
      ready.push(unit);
      continue;
    }
    hooks.onUpdate(unit.key, { status: "preparing", error: undefined, processError: undefined });
    const files: UploadFile[] = [];
    let failure: unknown = null;
    for (const file of unit.files) {
      if (file.prepared) {
        files.push(file);
        continue;
      }
      try {
        files.push(await prepareImage(file, { index: done + 1, now }));
      } catch (error) {
        failure = error;
      }
      done += 1;
      if (!failure && done < total) hooks.onPrepareStep(done + 1, total);
      if (failure) break;
    }
    if (failure) {
      // 本地压缩失败没有服务端文案，用固定说明代替原生错误串
      console.warn("[capture] 图片压缩失败", { key: unit.key, error: failure });
      hooks.onUpdate(unit.key, { status: "failed", error: IMAGE_PREPARE_ERROR });
      compressed.push(unit);
      continue;
    }
    const next: CaptureSubmitUnit = { ...unit, files };
    compressed.push(next);
    ready.push(next);
  }
  return { units: compressed, ready };
}

export function CaptureScreen() {
  const { token } = useAuth();
  const insets = useSafeAreaInsets();
  // iOS 键盘浮在页面上方，需自己把提交条抬起来；Android 走窗口 resize，不再叠加
  const keyboardHeight = useKeyboardHeight(insets.bottom);
  const keyboardPad = Platform.OS === "ios" ? keyboardHeight : 0;
  const [page, setPage] = useState<CapturePage>("entry");
  const [draft, setDraft] = useState<CaptureDraft | null>(null);
  const [session, setSession] = useState<CaptureSession | null>(null);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [notice, setNotice] = useState<PermissionKind | null>(null);
  const [albumOpen, setAlbumOpen] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [draftError, setDraftError] = useState("");
  // 提交重入锁：状态更新是异步的，连点两次可能都在 running 变 true 之前进来
  const submittingRef = useRef(false);

  const projectsQuery = useQuery({
    queryKey: ["projects", "mobile-capture"],
    queryFn: () => getProjects(token as string),
    enabled: Boolean(token),
  });
  const projects = projectsQuery.data ?? [];
  const running = Boolean(session?.running);

  const runUnits = useCallback(
    async (units: CaptureSubmitUnit[], meta: SessionMeta) => {
      if (!token || submittingRef.current) return;
      submittingRef.current = true;
      const update = (key: string, patch: Partial<CaptureResult>) =>
        setSession((previous) =>
          previous
            ? {
                ...previous,
                results: previous.results.map((item) =>
                  item.key === key ? { ...item, ...patch } : item,
                ),
              }
            : previous,
        );
      const setPreparing = (next: CaptureSession["preparing"]) =>
        setSession((previous) => (previous ? { ...previous, preparing: next } : previous));
      try {
        // 压缩在提交覆盖层内进行：连点两下也只会压一次、传一次
        const { units: compressed, ready } = await compressUnits(units, {
          onPrepareStart: (total) => setPreparing({ total, current: 1 }),
          onPrepareStep: (current, total) => setPreparing({ total, current }),
          onUpdate: update,
        });
        setSession((previous) =>
          previous
            ? {
                ...previous,
                preparing: null,
                units: previous.units.map(
                  (unit) => compressed.find((item) => item.key === unit.key) ?? unit,
                ),
              }
            : previous,
        );
        await submitCaptureUnits(ready, {
          upload: async (unit) => {
            const source = await uploadSource({
              token,
              unit,
              note: meta.note,
              projectId: meta.projectId,
            });
            return source.id;
          },
          triggerProcessing: (sourceId) => triggerSourceProcessing(token, sourceId),
          onUpdate: update,
        });
      } finally {
        submittingRef.current = false;
        // 提交结束一律停留在结果页，由用户点底部的「回到收集」返回
        setSession((previous) =>
          previous ? { ...previous, running: false, preparing: null } : previous,
        );
      }
    },
    [token],
  );

  /** 回到入口页并丢弃草稿；提交进行中不可离开覆盖层。 */
  function backToEntry() {
    if (running) return;
    setDraft(null);
    setDraftError("");
    setNotice(null);
    setPage("entry");
  }

  /** 覆盖层关闭 / 「回到收集」：清空草稿、提交会话与批次键，回入口页。 */
  function closeSubmission() {
    setSubmitOpen(false);
    setSession(null);
    setDraft(null);
    setDraftError("");
    setNotice(null);
    setPage("entry");
  }

  function openDraft(next: CaptureDraft) {
    setDraftError("");
    setDraft(next);
    setPage("form");
  }

  /** 选择器一返回就直接进采集页；压缩与上传都放到提交覆盖层里做。 */
  function openImagesDraft(assets: PickedAsset[], kind: CaptureKind) {
    if (assets.length === 0) return;
    setDraftError("");
    openDraft(emptyDraft(kind, draftImages(assets)));
  }

  async function onCamera() {
    setDraftError("");
    try {
      if (!(await ensurePermission("camera"))) {
        setNotice("camera");
        setPage("permission");
        return;
      }
      const asset = await capturePhoto();
      if (!asset) return;
      openImagesDraft([asset], "camera");
    } catch {
      setDraftError("无法打开系统相机，请稍后重试。");
    }
  }

  async function onAlbumEntry() {
    setDraftError("");
    try {
      if (!(await ensurePermission("album"))) {
        setNotice("album");
        setPage("permission");
        return;
      }
      setAlbumOpen(true);
    } catch {
      setDraftError("无法检查相册权限，请稍后重试。");
    }
  }

  async function onAlbumKind(kind: CaptureKind) {
    setAlbumOpen(false);
    setDraftError("");
    try {
      const assets = await pickImages();
      openImagesDraft(assets, kind);
    } catch {
      setDraftError("无法打开系统相册，请稍后重试。");
    }
  }

  async function onRetake() {
    setDraftError("");
    try {
      const asset = await capturePhoto();
      if (!asset) return;
      openImagesDraft([asset], "camera");
    } catch {
      setDraftError("无法打开系统相机，请稍后重试。");
    }
  }

  async function onFillFromClipboard() {
    const text = await readClipboardText();
    if (!text) {
      setDraftError("剪贴板里没有文字。");
      return;
    }
    setDraftError("");
    setDraft((previous) => (previous ? { ...previous, text } : previous));
  }

  async function onSubmit() {
    if (!draft || !token || running || submittingRef.current) return;
    setDraftError("");
    // 一次采集动作一个批次 UUID；重试沿用同一批次的同一序号键
    const batchId = newBatchId();
    let units: CaptureSubmitUnit[];
    try {
      units = createCaptureSubmitUnits({
        batchId,
        kind: draft.kind,
        files: draft.images,
        text: draft.text,
      });
    } catch (error) {
      setDraftError(toCaptureMessage(error));
      return;
    }
    const meta: SessionMeta = {
      kind: draft.kind,
      note: draft.note.trim(),
      projectId: draft.projectId,
    };
    const results = createCaptureResults(units);
    setSession({ batchId, ...meta, units, results, running: true, preparing: null });
    setSubmitOpen(true);
    await runUnits(units, meta);
  }

  async function onRetryUnits(keys: string[]) {
    if (!session || running || submittingRef.current) return;
    const units = session.units.filter((unit) => keys.includes(unit.key));
    if (units.length === 0) return;
    setSession({ ...session, running: true });
    await runUnits(units, {
      kind: session.kind,
      note: session.note,
      projectId: session.projectId,
    });
  }

  async function onRetryProcessing(key: string, sourceId: number) {
    if (!token) return;
    const clear = () =>
      setSession((previous) =>
        previous
          ? {
              ...previous,
              results: previous.results.map((item) =>
                item.key === key ? { ...item, processError: undefined } : item,
              ),
            }
          : previous,
      );
    const keep = (error: unknown) =>
      setSession((previous) =>
        previous
          ? {
              ...previous,
              results: previous.results.map((item) =>
                item.key === key ? { ...item, processError: toCaptureMessage(error) } : item,
              ),
            }
          : previous,
      );
    try {
      await triggerSourceProcessing(token, sourceId);
      clear();
    } catch (error) {
      keep(error);
    }
  }

  const projectName =
    draft?.projectId != null
      ? (projects.find((project) => project.id === draft.projectId)?.name ?? "未归属")
      : "未归属";
  const sessionProjectName =
    session?.projectId != null
      ? (projects.find((project) => project.id === session.projectId)?.name ?? "未归属")
      : "未归属";

  return (
    <SafeAreaView style={styles.page} edges={["top"]}>
      {page === "entry" ? (
        <ScrollView
          contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 24 }]}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.title}>收集</Text>
          <Text style={styles.subtitle}>先收进来，慢慢整理成自己的知识。</Text>
          <EntryRow
            onSelect={(entry) => {
              if (entry === "camera") void onCamera();
              else if (entry === "album") void onAlbumEntry();
              else openDraft(emptyDraft("text", []));
            }}
          />
          {draftError ? (
            <View style={styles.errorCard} accessibilityRole="alert">
              <Text style={styles.errorTitle}>采集未开始</Text>
              <Text style={styles.errorBody}>{draftError}</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : null}

      {page === "form" && draft ? (
        <View style={styles.fill}>
          <CaptureHeader title={FORM_TITLE[draft.kind]} onBack={backToEntry} />
          <ScrollView
            contentContainerStyle={[
              styles.content,
              { paddingBottom: 168 + keyboardPad + insets.bottom },
            ]}
            keyboardShouldPersistTaps="handled"
          >
            <CaptureForm
              draft={draft}
              projectName={projectName}
              error={draftError}
              onChangeText={(value) =>
                setDraft((previous) => (previous ? { ...previous, text: value } : previous))
              }
              onChangeNote={(value) =>
                setDraft((previous) => (previous ? { ...previous, note: value } : previous))
              }
              onRemoveImage={(index) =>
                setDraft((previous) =>
                  previous
                    ? { ...previous, images: previous.images.filter((_, position) => position !== index) }
                    : previous,
                )
              }
              onRetake={() => void onRetake()}
              onOpenProject={() => setProjectOpen(true)}
              onFillFromClipboard={() => void onFillFromClipboard()}
            />
          </ScrollView>
          <View style={[styles.footer, { bottom: keyboardPad }]}>
            <Text style={styles.footerHint}>{footerHint(draft)}</Text>
            <AppButton
              label="提交采集"
              variant="primary"
              block
              disabled={submitDisabled(draft)}
              onPress={() => void onSubmit()}
            />
            <Text style={styles.footerNote}>弱网重试不会重复生成来源；处理在提交后自动启动。</Text>
          </View>
        </View>
      ) : null}

      {page === "permission" && notice ? (
        <View style={styles.fill}>
          <CaptureHeader title={permissionTitle(notice)} onBack={backToEntry} />
          <ScrollView
            contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + 24 }]}
            keyboardShouldPersistTaps="handled"
          >
            <PermissionPage
              kind={notice}
              onOpenSettings={() => void openAppSettings()}
              onBack={backToEntry}
            />
          </ScrollView>
        </View>
      ) : null}

      <AlbumChoiceSheet
        visible={albumOpen}
        onChoose={(kind) => void onAlbumKind(kind)}
        onClose={() => setAlbumOpen(false)}
      />
      <ProjectSheet
        visible={projectOpen}
        projects={projects}
        selectedId={draft?.projectId ?? null}
        onSelect={(projectId) => {
          setDraft((previous) => (previous ? { ...previous, projectId } : previous));
          setProjectOpen(false);
        }}
        onClose={() => setProjectOpen(false)}
      />
      {session ? (
        <SubmitOverlay
          visible={submitOpen}
          session={session}
          projectName={sessionProjectName}
          onRetryUnit={(key) => void onRetryUnits([key])}
          onRetryFailed={() =>
            void onRetryUnits(
              session.results.filter((item) => item.status === "failed").map((item) => item.key),
            )
          }
          onRetryProcessing={(key, sourceId) => void onRetryProcessing(key, sourceId)}
          onClose={closeSubmission}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: theme.bg },
  fill: { flex: 1 },
  content: { paddingHorizontal: 16, paddingTop: 12 },
  title: { fontSize: 20, fontWeight: "700", color: theme.ink },
  subtitle: { marginTop: 4, marginBottom: 14, fontSize: 12, lineHeight: 19, color: theme.muted },
  footer: {
    position: "absolute",
    right: 0,
    left: 0,
    gap: 7,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 8,
    backgroundColor: theme.bg,
  },
  footerHint: { fontSize: 10.5, lineHeight: 16, textAlign: "center", color: theme.muted },
  footerNote: { fontSize: 10.5, lineHeight: 16, textAlign: "center", color: theme.muted },
  errorCard: {
    gap: 4,
    marginTop: 14,
    padding: 11,
    borderWidth: 1,
    borderLeftWidth: 3,
    borderColor: "#EFCACA",
    borderLeftColor: theme.error,
    borderRadius: 9,
    backgroundColor: theme.errorSoft,
  },
  errorTitle: { fontSize: 12.5, fontWeight: "700", color: theme.error },
  errorBody: { fontSize: 12, lineHeight: 19, color: "#7D2C2C" },
});
