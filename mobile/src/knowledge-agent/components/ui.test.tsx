import { fireEvent, render } from "@testing-library/react-native";
import { StyleSheet, Text } from "react-native";

import { Sheet } from "@/src/knowledge-agent/components/ui";

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

test("底部 Sheet 在加载与正文切换时保持稳定高度", async () => {
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
  expect(fixedHeightLayers).toHaveLength(1);

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
  ).toHaveLength(1);
});
