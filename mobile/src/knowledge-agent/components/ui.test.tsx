import { act, cleanup, fireEvent, render } from "@testing-library/react-native";
import { Animated, StyleSheet, Text } from "react-native";

import { Sheet } from "@/src/knowledge-agent/components/ui";

type AnimationEnd = ((result: { finished: boolean }) => void) | undefined;

function mockParallelAnimations() {
  const callbacks: AnimationEnd[] = [];
  const animations: Animated.CompositeAnimation[] = [];
  const spy = jest.spyOn(Animated, "parallel").mockImplementation(() => {
    const animation = {
      start: jest.fn((callback?: AnimationEnd) => callbacks.push(callback)),
      stop: jest.fn(),
      reset: jest.fn(),
    } as unknown as Animated.CompositeAnimation;
    animations.push(animation);
    return animation;
  });
  return { animations, callbacks, spy };
}

async function showModal(rendered: Awaited<ReturnType<typeof render>>) {
  await fireEvent(rendered.getByTestId("bottom-sheet-modal"), "show");
}

async function layoutPanel(rendered: Awaited<ReturnType<typeof render>>, height = 320) {
  await fireEvent(rendered.getByTestId("bottom-sheet-panel"), "layout", {
    nativeEvent: { layout: { x: 0, y: 0, width: 390, height } },
  });
}

afterEach(() => {
  cleanup();
  jest.restoreAllMocks();
});

test("普通共享 Sheet 仍支持关闭按钮和内容滚动容器", async () => {
  const onClose = jest.fn();
  const rendered = await render(
    <Sheet visible title="范围" onClose={onClose}>
      <Text>范围内容</Text>
    </Sheet>,
  );

  expect(rendered.getByText("范围内容")).toBeTruthy();
  await fireEvent.press(rendered.getByLabelText("关闭"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("减少动态效果时底部 Sheet 通过遮罩立即关闭", async () => {
  const onClose = jest.fn();
  const rendered = await render(
    <Sheet
      visible
      title="知识详情"
      onClose={onClose}
      presentation="bottom"
      reduceMotion
    >
      <Text>详情内容</Text>
    </Sheet>,
  );

  await fireEvent.press(rendered.getByLabelText("关闭弹层"));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test.each(["show-first", "layout-first"])(
  "底部 Sheet 等待原生显示和有效布局后只入场一次：%s",
  async (order) => {
    const animation = mockParallelAnimations();
    const onPresented = jest.fn();
    const rendered = await render(
      <Sheet
        visible
        title="知识详情"
        onClose={jest.fn()}
        presentation="bottom"
        onPresented={onPresented}
      >
        <Text>详情内容</Text>
      </Sheet>,
    );

    if (order === "show-first") await showModal(rendered);
    else await layoutPanel(rendered, 180);
    expect(animation.spy).not.toHaveBeenCalled();

    if (order === "show-first") await layoutPanel(rendered, 180);
    else await showModal(rendered);
    expect(animation.spy).toHaveBeenCalledTimes(1);
    expect(onPresented).not.toHaveBeenCalled();
    expect(
      StyleSheet.flatten(rendered.getByTestId("bottom-sheet-panel").props.style)?.transform,
    ).toEqual([{ translateY: 204 }]);

    await layoutPanel(rendered, 240);
    await rendered.rerender(
      <Sheet
        visible
        title="知识详情"
        onClose={jest.fn()}
        presentation="bottom"
        onPresented={onPresented}
      >
        <Text>刷新后的更长详情内容</Text>
      </Sheet>,
    );
    await layoutPanel(rendered, 360);
    expect(animation.spy).toHaveBeenCalledTimes(1);

    await act(() => animation.callbacks[0]?.({ finished: true }));
    expect(onPresented).toHaveBeenCalledTimes(1);
    expect(animation.spy).toHaveBeenCalledTimes(1);
  },
);

test("打开中关闭会作废旧入场回调，重新打开使用新的生命周期", async () => {
  const animation = mockParallelAnimations();
  const onClose = jest.fn();
  const onPresented = jest.fn();
  const renderSheet = (visible: boolean) => (
    <Sheet
      visible={visible}
      title="知识详情"
      onClose={onClose}
      presentation="bottom"
      onPresented={onPresented}
    >
      <Text>详情内容</Text>
    </Sheet>
  );
  const rendered = await render(renderSheet(true));
  await showModal(rendered);
  await layoutPanel(rendered, 220);
  expect(animation.callbacks).toHaveLength(1);

  await fireEvent(rendered.getByTestId("bottom-sheet-modal"), "requestClose");
  expect(animation.animations[0]?.stop).toHaveBeenCalledTimes(1);
  expect(animation.callbacks).toHaveLength(2);
  await act(() => animation.callbacks[0]?.({ finished: true }));
  expect(onPresented).not.toHaveBeenCalled();
  await act(() => animation.callbacks[1]?.({ finished: true }));
  expect(onClose).toHaveBeenCalledTimes(1);

  await rendered.rerender(renderSheet(false));
  await rendered.rerender(renderSheet(true));
  await showModal(rendered);
  await layoutPanel(rendered, 260);
  expect(animation.callbacks).toHaveLength(3);
  await act(() => animation.callbacks[1]?.({ finished: true }));
  expect(onClose).toHaveBeenCalledTimes(1);
  await act(() => animation.callbacks[2]?.({ finished: true }));
  expect(onPresented).toHaveBeenCalledTimes(1);
});

test("减少动态效果也等待双就绪且偏好变化不重播", async () => {
  const animation = mockParallelAnimations();
  const onPresented = jest.fn();
  const rendered = await render(
    <Sheet
      visible
      title="知识详情"
      onClose={jest.fn()}
      presentation="bottom"
      reduceMotion
      onPresented={onPresented}
    >
      <Text>详情内容</Text>
    </Sheet>,
  );

  await showModal(rendered);
  expect(onPresented).not.toHaveBeenCalled();
  await layoutPanel(rendered, 200);
  expect(onPresented).toHaveBeenCalledTimes(1);
  expect(animation.spy).not.toHaveBeenCalled();

  await rendered.rerender(
    <Sheet
      visible
      title="知识详情"
      onClose={jest.fn()}
      presentation="bottom"
      reduceMotion={false}
      onPresented={onPresented}
    >
      <Text>详情内容</Text>
    </Sheet>,
  );
  await layoutPanel(rendered, 220);
  expect(onPresented).toHaveBeenCalledTimes(1);
  expect(animation.spy).not.toHaveBeenCalled();
});

test("底部 Sheet 按当前内容自适应并受最大高度约束", async () => {
  const rendered = await render(
    <Sheet
      visible
      title="知识详情"
      onClose={jest.fn()}
      presentation="bottom"
      reduceMotion
    >
      <Text>短加载内容</Text>
    </Sheet>,
  );

  const fixedHeightLayers =
    rendered.root?.queryAll((node) => StyleSheet.flatten(node.props.style)?.height === "84%") ?? [];
  const cappedLayers =
    rendered.root?.queryAll((node) => StyleSheet.flatten(node.props.style)?.maxHeight === "84%") ?? [];
  expect(fixedHeightLayers).toHaveLength(0);
  expect(cappedLayers).toHaveLength(1);

  await rendered.rerender(
    <Sheet
      visible
      title="知识详情"
      onClose={jest.fn()}
      presentation="bottom"
      reduceMotion
    >
      <Text>{"长正文".repeat(100)}</Text>
    </Sheet>,
  );
  expect(
    rendered.root?.queryAll((node) => StyleSheet.flatten(node.props.style)?.height === "84%"),
  ).toHaveLength(0);
});
