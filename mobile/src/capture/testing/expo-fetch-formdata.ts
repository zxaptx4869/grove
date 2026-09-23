/**
 * 测试替身：模拟 Expo fetch 自己序列化 multipart 时的 FormData 契约。
 *
 * Expo 的 fetch 只接受 string 与带 `bytes()` 的部件（Blob / expo-file-system 的 File）；
 * RN 经典的 `{ uri, name, type }` 部件会抛 "Unsupported FormDataPart implementation"。
 * jest 里 Node 自带的 undici FormData 只接受真 Blob，与运行时行为不一致，所以测试中替换掉。
 */

type Part = [string, unknown];

export class ExpoFetchFormData {
  private parts: Part[] = [];

  append(name: string, value: unknown): void {
    const acceptable =
      typeof value === "string" ||
      (typeof value === "object" && value !== null && "bytes" in value);
    if (!acceptable) throw new TypeError("Unsupported FormDataPart implementation");
    this.parts.push([name, value]);
  }

  get(name: string): unknown {
    const found = this.parts.find(([key]) => key === name);
    return found ? found[1] : null;
  }

  getAll(name: string): unknown[] {
    return this.parts.filter(([key]) => key === name).map(([, value]) => value);
  }
}

/** 装上替身并返回还原函数。 */
export function installExpoFetchFormData(): () => void {
  const original = (globalThis as { FormData?: unknown }).FormData;
  (globalThis as { FormData?: unknown }).FormData = ExpoFetchFormData;
  return () => {
    (globalThis as { FormData?: unknown }).FormData = original;
  };
}
