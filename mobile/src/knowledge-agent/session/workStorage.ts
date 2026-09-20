import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import type { PendingSubmission } from "@/src/knowledge-agent/state/submission";
import type { KnowledgeScopeChangeRequest } from "@/src/knowledge-agent/types";

const STORAGE_PREFIX = "grove_mobile_dialogue";
const CHUNK_SIZE = 400;

export interface DialogueIdentity {
  userId: number;
  workspaceId: number;
}

export interface PersistedDialogueWork {
  version: 1;
  conversationId: number | null;
  runId: number | null;
  scope: KnowledgeScopeChangeRequest;
  input: string;
  pending: PendingSubmission | null;
  updatedAt: string;
}

interface ChunkManifest {
  version: 1;
  count: number;
}

function identityKey(identity: DialogueIdentity): string {
  return `${identity.userId}_${identity.workspaceId}`;
}

function workKey(identity: DialogueIdentity): string {
  return `${STORAGE_PREFIX}_work_${identityKey(identity)}`;
}

function scopeKey(identity: DialogueIdentity): string {
  return `${STORAGE_PREFIX}_scope_${identityKey(identity)}`;
}

const platformStorage = {
  get: (key: string) =>
    Platform.OS === "web"
      ? Promise.resolve(globalThis.localStorage.getItem(key))
      : SecureStore.getItemAsync(key),
  set: (key: string, value: string) =>
    Platform.OS === "web"
      ? Promise.resolve(globalThis.localStorage.setItem(key, value))
      : SecureStore.setItemAsync(key, value),
  remove: (key: string) =>
    Platform.OS === "web"
      ? Promise.resolve(globalThis.localStorage.removeItem(key))
      : SecureStore.deleteItemAsync(key),
};

function splitValue(value: string): string[] {
  const characters = Array.from(value);
  const chunks: string[] = [];
  for (let index = 0; index < characters.length; index += CHUNK_SIZE) {
    chunks.push(characters.slice(index, index + CHUNK_SIZE).join(""));
  }
  return chunks.length > 0 ? chunks : [""];
}

async function readManifest(key: string): Promise<ChunkManifest | null> {
  const value = await platformStorage.get(`${key}:manifest`);
  if (!value) return null;
  const parsed = JSON.parse(value) as Partial<ChunkManifest>;
  if (parsed.version !== 1 || !Number.isInteger(parsed.count) || (parsed.count ?? 0) < 1) {
    throw new Error("移动对话恢复记录格式无效");
  }
  return parsed as ChunkManifest;
}

async function removeChunked(key: string): Promise<void> {
  const manifest = await readManifest(key).catch(() => null);
  if (manifest) {
    await Promise.all(
      Array.from({ length: manifest.count }, (_, index) =>
        platformStorage.remove(`${key}:chunk:${index}`),
      ),
    );
  }
  await platformStorage.remove(`${key}:manifest`);
}

async function writeChunked(key: string, value: string): Promise<void> {
  const previous = await readManifest(key).catch(() => null);
  const chunks = splitValue(value);
  await Promise.all(
    chunks.map((chunk, index) => platformStorage.set(`${key}:chunk:${index}`, chunk)),
  );
  await platformStorage.set(
    `${key}:manifest`,
    JSON.stringify({ version: 1, count: chunks.length } satisfies ChunkManifest),
  );
  if (previous && previous.count > chunks.length) {
    await Promise.all(
      Array.from({ length: previous.count - chunks.length }, (_, offset) =>
        platformStorage.remove(`${key}:chunk:${chunks.length + offset}`),
      ),
    );
  }
}

async function readChunked(key: string): Promise<string | null> {
  const manifest = await readManifest(key);
  if (!manifest) return null;
  const chunks = await Promise.all(
    Array.from({ length: manifest.count }, (_, index) =>
      platformStorage.get(`${key}:chunk:${index}`),
    ),
  );
  if (chunks.some((chunk) => chunk === null)) {
    throw new Error("移动对话恢复记录不完整");
  }
  return chunks.join("");
}

export async function readDialogueWork(
  identity: DialogueIdentity,
): Promise<PersistedDialogueWork | null> {
  const value = await readChunked(workKey(identity));
  if (!value) return null;
  const parsed = JSON.parse(value) as Partial<PersistedDialogueWork>;
  if (parsed.version !== 1 || typeof parsed.input !== "string" || !parsed.scope) {
    throw new Error("移动对话恢复记录格式无效");
  }
  return parsed as PersistedDialogueWork;
}

export function writeDialogueWork(
  identity: DialogueIdentity,
  work: PersistedDialogueWork,
): Promise<void> {
  return writeChunked(workKey(identity), JSON.stringify(work));
}

export function clearDialogueWork(identity: DialogueIdentity): Promise<void> {
  return removeChunked(workKey(identity));
}

export async function readLastDialogueScope(
  identity: DialogueIdentity,
): Promise<KnowledgeScopeChangeRequest | null> {
  const value = await readChunked(scopeKey(identity));
  if (!value) return null;
  const parsed = JSON.parse(value) as Partial<KnowledgeScopeChangeRequest>;
  if (parsed.scopeType !== "workspace" && parsed.scopeType !== "project") {
    throw new Error("移动对话范围记录格式无效");
  }
  return parsed as KnowledgeScopeChangeRequest;
}

export function writeLastDialogueScope(
  identity: DialogueIdentity,
  scope: KnowledgeScopeChangeRequest,
): Promise<void> {
  return writeChunked(scopeKey(identity), JSON.stringify(scope));
}

export async function clearDialogueIdentityStorage(
  identity: DialogueIdentity,
): Promise<void> {
  await Promise.all([removeChunked(workKey(identity)), removeChunked(scopeKey(identity))]);
}
