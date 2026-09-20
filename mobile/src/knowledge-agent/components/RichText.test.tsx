import { fireEvent, render } from "@testing-library/react-native";
import { Linking, StyleSheet } from "react-native";

import { RichText } from "@/src/knowledge-agent/components/RichText";

afterEach(() => {
  jest.restoreAllMocks();
});

test("用原生组件展示 Markdown，文本可选择且宽内容可水平滚动", async () => {
  const rendered = await render(
    <RichText>{`## 标题

正文包含 **重点** 和列表：

- 第一项
- 第二项

\`\`\`text
very-long-code-line-without-breaking
\`\`\`

| A | B |
| - | - |
| 1 | 2 |`}</RichText>,
  );

  expect(rendered.getByText("标题")).toBeTruthy();
  expect(rendered.getByText("重点")).toBeTruthy();
  expect(
    rendered.root?.queryAll((node) => node.props.selectable === true).length,
  ).toBeGreaterThan(0);
  expect(
    rendered.root?.queryAll((node) => node.props.horizontal === true).length,
  ).toBeGreaterThanOrEqual(2);
});

test("仅打开安全链接，图片不发起加载且原始 HTML 不执行", async () => {
  const openUrl = jest.spyOn(Linking, "openURL").mockResolvedValue(undefined);
  const rendered = await render(
    <RichText>{`[官方页面](https://example.com)

[危险协议](javascript:alert(1))

![示例图](https://example.com/image.png)

<b>原始标签</b>`}</RichText>,
  );

  fireEvent.press(rendered.getByText("官方页面"));
  expect(openUrl).toHaveBeenCalledWith("https://example.com");
  expect(openUrl).toHaveBeenCalledTimes(1);
  expect(rendered.getByText("[危险协议](javascript:alert(1))")).toBeTruthy();
  expect(rendered.root?.queryAll((node) => node.props.source != null)).toHaveLength(0);
  expect(rendered.getByText("[图片已隐藏]")).toBeTruthy();
  expect(rendered.getByText("<b>原始标签</b>")).toBeTruthy();
});

test("长列表正文受可视宽度约束并允许收缩换行", async () => {
  const rendered = await render(
    <RichText>{`- **短期高浓度接触：**刺激眼睛、鼻子、咽喉，引起流泪和呼吸道不适
- 普通长列表文本也必须在移动端屏幕范围内完整换行显示`}</RichText>,
  );

  const styles =
    rendered.root
      ?.queryAll((node) => node.props.style != null)
      .map((node) => StyleSheet.flatten(node.props.style)) ?? [];
  expect(
    styles.some(
      (style) =>
        style?.flexGrow === 1 &&
        style?.flexShrink === 1 &&
        style?.flexBasis === 0 &&
        style?.minWidth === 0,
    ),
  ).toBe(true);
  expect(
    styles.some(
      (style) =>
        style?.width === "100%" &&
        style?.maxWidth === "100%" &&
        style?.flexDirection === "row",
    ),
  ).toBe(true);
});
