/** 文本采集的剪贴板读取。 */

import * as Clipboard from "expo-clipboard";

export async function readClipboardText(): Promise<string> {
  return (await Clipboard.getStringAsync()).trim();
}
