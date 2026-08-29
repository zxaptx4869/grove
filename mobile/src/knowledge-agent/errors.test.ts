import {
  classifyKnowledgeAgentError,
  KnowledgeAgentError,
} from "@/src/knowledge-agent/errors";

test("401 鉴权失效、409 冲突、404 与网络错误分类", () => {
  const auth = classifyKnowledgeAgentError({ status: 401, message: "未授权" });
  expect(auth.kind).toBe("auth");
  expect(auth.retryable).toBe(false);

  const conflict = classifyKnowledgeAgentError({
    status: 409,
    message: "存在进行中的问答",
  });
  expect(conflict.kind).toBe("conflict");

  const notFound = classifyKnowledgeAgentError({ status: 404 });
  expect(notFound.kind).toBe("not_found");

  const network = classifyKnowledgeAgentError(new TypeError("Network request failed"));
  expect(network.kind).toBe("network");
  expect(network.retryable).toBe(true);
});

test("AbortError 视为取消而非网络失败", () => {
  const aborted = new DOMException("Aborted", "AbortError");
  const classified = classifyKnowledgeAgentError(aborted);
  expect(classified.kind).toBe("cancelled");
  expect(classified.retryable).toBe(false);
});

test("KnowledgeAgentError 保持原分类", () => {
  const original = new KnowledgeAgentError({
    kind: "server",
    status: 500,
    message: "服务异常",
    retryable: true,
  });
  const classified = classifyKnowledgeAgentError(original);
  expect(classified).toBe(original);
  expect(classified.kind).toBe("server");
});
