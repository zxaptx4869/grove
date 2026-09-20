import { act, renderHook, waitFor } from "@testing-library/react-native";

import { mobileLogout } from "@/src/api";
import { AuthProvider, useAuth } from "@/src/auth";
import { clearDialogueIdentityStorage } from "@/src/knowledge-agent/session/workStorage";

const mockGetItemAsync = jest.fn(async (_key: string) => "saved-token");
const mockDeleteItemAsync = jest.fn(async (_key: string) => undefined);

jest.mock("expo-secure-store", () => ({
  getItemAsync: (key: string) => mockGetItemAsync(key),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: (key: string) => mockDeleteItemAsync(key),
}));

jest.mock("@/src/api", () => ({
  getMe: jest.fn(async () => ({
    user: { id: 4, username: "user-4" },
    workspace: { id: 9, name: "workspace-9" },
  })),
  mobileLogin: jest.fn(),
  mobileLogout: jest.fn(async () => ({ ok: true })),
}));

jest.mock("@/src/knowledge-agent/session/workStorage", () => ({
  clearDialogueIdentityStorage: jest.fn(async () => undefined),
}));

test("退出登录清理当前用户与 Workspace 的移动对话记录", async () => {
  const rendered = await renderHook(() => useAuth(), {
    wrapper: ({ children }) => <AuthProvider>{children}</AuthProvider>,
  });
  await waitFor(() => expect(rendered.result.current.loading).toBe(false));
  expect(rendered.result.current.me?.workspace.id).toBe(9);

  await act(async () => {
    await rendered.result.current.signOut();
  });
  expect(mobileLogout).toHaveBeenCalledWith("saved-token");
  expect(clearDialogueIdentityStorage).toHaveBeenCalledWith({
    userId: 4,
    workspaceId: 9,
  });
  expect(mockDeleteItemAsync).toHaveBeenCalledWith("grove_mobile_session");
  expect(rendered.result.current.token).toBeNull();
  expect(rendered.result.current.me).toBeNull();
});
