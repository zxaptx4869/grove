import { act, cleanup, renderHook, waitFor } from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";

import {
  DialogueSessionProvider,
  useDialogueSession,
} from "@/src/knowledge-agent/session/DialogueSessionProvider";
import { clearDialogueIdentityStorage } from "@/src/knowledge-agent/session/workStorage";
import { createPendingSubmission } from "@/src/knowledge-agent/state/submission";

let mockMe = {
  user: { id: 1, username: "user-1" },
  workspace: { id: 10, name: "workspace-10" },
};
const mockStorage = new Map<string, string>();

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ token: "token", me: mockMe, loading: false }),
}));

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => {
    if (!/^[A-Za-z0-9._-]+$/.test(key)) {
      throw new Error("Invalid key provided to SecureStore");
    }
    return mockStorage.get(key) ?? null;
  }),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (!/^[A-Za-z0-9._-]+$/.test(key)) {
      throw new Error("Invalid key provided to SecureStore");
    }
    mockStorage.set(key, value);
  }),
  deleteItemAsync: jest.fn(async (key: string) => {
    if (!/^[A-Za-z0-9._-]+$/.test(key)) {
      throw new Error("Invalid key provided to SecureStore");
    }
    mockStorage.delete(key);
  }),
}));

function wrapper({ children }: React.PropsWithChildren) {
  return <DialogueSessionProvider>{children}</DialogueSessionProvider>;
}

afterEach(() => {
  cleanup();
  mockStorage.clear();
  mockMe = {
    user: { id: 1, username: "user-1" },
    workspace: { id: 10, name: "workspace-10" },
  };
  jest.clearAllMocks();
});

test("无待恢复工作时冷启动保持空白新对话和最后有效范围", async () => {
  const first = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(first.result.current.bootStatus).toBe("ready"));
  expect(first.result.current.choice).toBe("draft");

  await act(async () => {
    first.result.current.update({
      scope: { scopeType: "project", projectId: 5, projectName: "装修" },
    });
  });
  await waitFor(() =>
    expect([...mockStorage.keys()].some((key) => key.includes("_scope_1_10"))).toBe(true),
  );
  expect([...mockStorage.keys()].every((key) => /^[A-Za-z0-9._-]+$/.test(key))).toBe(true);
  await first.unmount();

  const restored = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(restored.result.current.bootStatus).toBe("ready"));
  expect(restored.result.current.choice).toBe("draft");
  expect(restored.result.current.input).toBe("");
  expect(restored.result.current.scope).toEqual({
    scopeType: "project",
    projectId: 5,
    projectName: "装修",
  });
});

test("销毁并重建后恢复输入、原会话和稳定提交标识", async () => {
  const first = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(first.result.current.bootStatus).toBe("ready"));
  const pending = {
    ...createPendingSubmission({ text: "未确认问题", contextMode: "auto" }),
    conversationId: 7,
  };
  await act(async () => {
    first.result.current.update({
      choice: 7,
      input: "未发送草稿".repeat(120),
      pending,
      pendingState: "result_unknown",
      recoveryRun: { conversationId: 7, runId: 70 },
    });
  });
  await waitFor(() =>
    expect(
      [...mockStorage.keys()].filter((key) => key.includes("_work_1_10__chunk_")).length,
    ).toBeGreaterThan(1),
  );
  await first.unmount();

  const restored = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(restored.result.current.bootStatus).toBe("ready"));
  expect(restored.result.current.choice).toBe(7);
  expect(restored.result.current.input).toBe("未发送草稿".repeat(120));
  expect(restored.result.current.pending?.clientMessageId).toBe(pending.clientMessageId);
  expect(restored.result.current.pendingState).toBe("result_unknown");
  expect(restored.result.current.recoveryRun).toEqual({ conversationId: 7, runId: 70 });
});

test("身份或 Workspace 变化后不读取另一身份的恢复记录", async () => {
  const rendered = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("ready"));
  await act(async () => {
    rendered.result.current.update({ input: "身份一的输入" });
  });
  await waitFor(() =>
    expect([...mockStorage.keys()].some((key) => key.includes("_work_1_10"))).toBe(true),
  );

  mockMe = {
    user: { id: 2, username: "user-2" },
    workspace: { id: 20, name: "workspace-20" },
  };
  await rendered.rerender(undefined);
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("ready"));
  expect(rendered.result.current.choice).toBe("draft");
  expect(rendered.result.current.input).toBe("");
  expect(
    [...mockStorage.entries()].some(
      ([key, value]) => key.includes("_2_20") && value.includes("身份一的输入"),
    ),
  ).toBe(false);
});

test("退出当前身份时可清理范围与工作记录", async () => {
  const rendered = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("ready"));
  await act(async () => {
    rendered.result.current.update({ input: "待清理" });
  });
  await waitFor(() => expect(mockStorage.size).toBeGreaterThan(0));

  await clearDialogueIdentityStorage({ userId: 1, workspaceId: 10 });
  expect([...mockStorage.keys()].filter((key) => key.includes("_1_10"))).toEqual([]);
});

test("本地恢复记录损坏时不静默回退，修复后可重试", async () => {
  const manifestKey = "grove_mobile_dialogue_work_1_10__manifest";
  mockStorage.set(manifestKey, "{无效");
  const rendered = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("error"));
  expect(rendered.result.current.bootError).not.toBeNull();

  mockStorage.delete(manifestKey);
  await act(async () => {
    rendered.result.current.retryBootstrap();
  });
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("ready"));
  expect(rendered.result.current.choice).toBe("draft");
});

test("退出恢复在安全存储清理失败时仍解除页面阻塞", async () => {
  const manifestKey = "grove_mobile_dialogue_work_1_10__manifest";
  mockStorage.set(manifestKey, "{无效");
  const rendered = await renderHook(() => useDialogueSession(), { wrapper });
  await waitFor(() => expect(rendered.result.current.bootStatus).toBe("error"));
  jest.mocked(SecureStore.deleteItemAsync).mockRejectedValueOnce(new Error("存储暂不可用"));

  await act(async () => {
    await rendered.result.current.exitRecovery();
  });

  expect(rendered.result.current.bootStatus).toBe("ready");
  expect(rendered.result.current.bootError).toBeNull();
  expect(rendered.result.current.choice).toBe("draft");
  expect(rendered.result.current.input).toBe("");

  await act(async () => {
    rendered.result.current.update({ input: "退出恢复后可继续输入" });
  });
  await waitFor(() =>
    expect([...mockStorage.values()].some((value) => value.includes("退出恢复后可继续输入"))).toBe(
      true,
    ),
  );
});
