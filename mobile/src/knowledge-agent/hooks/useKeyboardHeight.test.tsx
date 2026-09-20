import { act, renderHook } from "@testing-library/react-native";
import { Keyboard, Platform } from "react-native";

import { useKeyboardHeight } from "@/src/knowledge-agent/hooks/useKeyboardHeight";

type KeyboardHandler = (event: { endCoordinates: { height: number } }) => void;

const handlers: Record<string, KeyboardHandler> = {};

jest.spyOn(Keyboard, "addListener").mockImplementation(
  ((event: string, handler: KeyboardHandler) => {
    handlers[event] = handler;
    return { remove: jest.fn() };
  }) as never,
);

test("键盘显示更新高度、隐藏归零", async () => {
  const rendered = await renderHook(() => useKeyboardHeight(0));
  expect(rendered.result.current).toBe(0);

  await act(async () => {
    handlers.keyboardWillShow?.({ endCoordinates: { height: 336 } });
  });
  expect(rendered.result.current).toBe(336);

  await act(async () => {
    handlers.keyboardWillHide?.({ endCoordinates: { height: 0 } });
  });
  expect(rendered.result.current).toBe(0);
  await rendered.unmount();
});

test("Android 键盘高度补上底部 inset", async () => {
  const originalOS = Platform.OS;
  Object.defineProperty(Platform, "OS", {
    get: () => "android",
    configurable: true,
  });
  try {
    const rendered = await renderHook(() => useKeyboardHeight(24));
    await act(async () => {
      handlers.keyboardDidShow?.({ endCoordinates: { height: 336 } });
    });
    expect(rendered.result.current).toBe(360);
    await rendered.unmount();
  } finally {
    Object.defineProperty(Platform, "OS", {
      get: () => originalOS,
      configurable: true,
    });
  }
});
