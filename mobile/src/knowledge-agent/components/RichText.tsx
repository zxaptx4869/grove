import { memo, type ReactNode } from "react";
import { Linking, ScrollView, StyleSheet, Text, View } from "react-native";
import Markdown, {
  MarkdownIt,
  renderRules,
  type ASTNode,
  type MarkdownStyles,
  type RenderRules,
} from "react-native-markdown-renderer";

import { theme } from "@/src/theme";

const markdown = MarkdownIt({ html: false, linkify: false, typographer: false });

function heading(
  node: ASTNode,
  children: ReactNode[],
  _parents: ASTNode[],
  styles: MarkdownStyles,
) {
  return (
    <Text
      key={node.key}
      selectable
      style={[styles.heading as object, styles[node.type] as object]}
    >
      {children}
    </Text>
  );
}

function codeBlock(node: ASTNode, _children: ReactNode[], _parents: ASTNode[], styles: MarkdownStyles) {
  return (
    <ScrollView
      key={node.key}
      horizontal
      nestedScrollEnabled
      showsHorizontalScrollIndicator
      style={richStyles.wideContent}
      contentContainerStyle={richStyles.wideContentInner}
    >
      <Text selectable style={styles.codeBlock as object}>
        {node.content.replace(/\n$/, "")}
      </Text>
    </ScrollView>
  );
}

const rules: RenderRules = {
  textgroup: (node, children, _parents, styles) => (
    <Text key={node.key} selectable style={styles.text as object}>
      {children}
    </Text>
  ),
  paragraph: (node, children, _parents, styles) => (
    <Text key={node.key} selectable style={styles.paragraph as object}>
      {children}
    </Text>
  ),
  heading1: heading,
  heading2: heading,
  heading3: heading,
  heading4: heading,
  heading5: heading,
  heading6: heading,
  code_block: codeBlock,
  fence: codeBlock,
  table: (node, children, parents, styles) => (
    <ScrollView
      key={node.key}
      horizontal
      nestedScrollEnabled
      showsHorizontalScrollIndicator
      style={richStyles.wideContent}
    >
      <View style={richStyles.tableWidth}>
        {renderRules.table(node, children, parents, styles)}
      </View>
    </ScrollView>
  ),
  image: (node) => (
    <Text key={node.key} selectable style={richStyles.imageFallback}>
      {node.attributes.alt ? `[图片：${node.attributes.alt}]` : "[图片已隐藏]"}
    </Text>
  ),
};

const normalStyles = {
  text: { color: theme.ink, fontSize: 14, lineHeight: 23 },
  paragraph: { color: theme.ink, fontSize: 14, lineHeight: 23, marginBottom: 10 },
  heading: { color: theme.ink, fontWeight: "700" as const, marginTop: 10, marginBottom: 6 },
  heading1: { fontSize: 20, lineHeight: 28 },
  heading2: { fontSize: 18, lineHeight: 26 },
  heading3: { fontSize: 16, lineHeight: 24 },
  heading4: { fontSize: 15, lineHeight: 23 },
  heading5: { fontSize: 14, lineHeight: 22 },
  heading6: { fontSize: 14, lineHeight: 22 },
  headingContainer: { marginTop: 0, marginBottom: 0 },
  blockquote: {
    borderLeftWidth: 3,
    borderLeftColor: theme.border,
    paddingLeft: 10,
    paddingRight: 0,
    marginBottom: 10,
  },
  list: { marginBottom: 10 },
  listUnorderedItemIcon: { color: theme.muted, lineHeight: 23 },
  listOrderedItemIcon: { color: theme.muted, lineHeight: 23 },
  codeInline: { color: theme.ink, backgroundColor: theme.soft, fontSize: 13 },
  codeBlock: {
    color: theme.ink,
    backgroundColor: theme.soft,
    fontSize: 13,
    lineHeight: 20,
    padding: 10,
    marginBottom: 0,
  },
  link: { color: theme.green, textDecorationLine: "underline" as const },
  table: { borderColor: theme.border, marginBottom: 0 },
  tableHeader: { backgroundColor: theme.soft },
  tableHeaderCell: { borderColor: theme.border, minWidth: 120 },
  tableRowCell: { borderColor: theme.border, minWidth: 120 },
  hr: { height: 1, backgroundColor: theme.border, marginVertical: 12 },
};

const mutedStyles = {
  ...normalStyles,
  text: { color: theme.muted, fontSize: 13, lineHeight: 21 },
  paragraph: { color: theme.muted, fontSize: 13, lineHeight: 21, marginBottom: 8 },
};

function openSafeLink(url: string) {
  let protocol: string;
  try {
    protocol = new URL(url).protocol.toLowerCase();
  } catch {
    return;
  }
  if (!['https:', 'http:', 'mailto:'].includes(protocol)) return;
  void Linking.openURL(url).catch(() => undefined);
}

export const RichText = memo(function RichText({
  children,
  tone = "normal",
}: {
  children: string;
  tone?: "normal" | "muted";
}) {
  return (
    <Markdown
      markdownit={markdown}
      rules={rules}
      style={tone === "muted" ? mutedStyles : normalStyles}
      allowedImageHandlers={[]}
      defaultImageHandler={null}
      onLinkPress={openSafeLink}
    >
      {children}
    </Markdown>
  );
});

const richStyles = StyleSheet.create({
  wideContent: { maxWidth: "100%", marginBottom: 10 },
  wideContentInner: { paddingRight: 4 },
  tableWidth: { minWidth: 520 },
  imageFallback: { color: theme.muted, fontSize: 12, lineHeight: 20 },
});
