import {
  attachConversation,
  canRetrySubmission,
  createPendingSubmission,
  markConfirmed,
  markConflict,
  retrySubmissionWithNewId,
} from "@/src/knowledge-agent/state/submission";

const fixedId = () => "fixed-client-id";

test("草稿首次发送生成稳定幂等键并保留对话 id", () => {
  const pending = createPendingSubmission({
    text: "  第一个问题  ",
    contextMode: "auto",
    answerMode: "auto",
    resultMode: "entries",
    basisMode: "auto",
    random: fixedId,
  });
  expect(pending.clientMessageId).toBe("fixed-client-id");
  expect(pending.basisMode).toBe("auto");
  expect(pending.phase).toBe("creating_conversation");
  expect(pending.conversationId).toBeNull();

  // 创建成功但提交结果未知：保留 conversation_id 与同一幂等键
  const afterCreate = attachConversation(pending, 42);
  expect(afterCreate.conversationId).toBe(42);
  expect(afterCreate.clientMessageId).toBe("fixed-client-id");
  expect(canRetrySubmission(afterCreate)).toBe(true);
});

test("确定提交成功前可重复重试，成功后清空 pending 不可重试", () => {
  const pending = attachConversation(
    createPendingSubmission({
      text: "问题",
      contextMode: "continue",
      answerMode: "investigate",
      resultMode: "answer",
      basisMode: "knowledge_only",
      random: fixedId,
    }),
    7,
  );
  expect(canRetrySubmission(pending)).toBe(true);
  expect(pending.basisMode).toBe("knowledge_only");
  const confirmed = markConfirmed(pending);
  expect(confirmed.phase).toBe("confirmed");
  expect(canRetrySubmission(confirmed)).toBe(false);
});

test("终态 failed 的重新提问生成新 client_message_id", () => {
  const pending = attachConversation(
    createPendingSubmission({
      text: "同一个问题",
      contextMode: "auto",
      answerMode: "auto",
      resultMode: "auto",
      basisMode: "auto",
      random: fixedId,
    }),
    3,
  );
  const retried = retrySubmissionWithNewId(pending, () => "new-client-id");
  expect(retried.clientMessageId).toBe("new-client-id");
  expect(retried.clientMessageId).not.toBe(pending.clientMessageId);
  expect(retried.conversationId).toBeNull();
  expect(retried.text).toBe("同一个问题");
});

test("模式纠正网络重试保留来源 Run", () => {
  const pending = createPendingSubmission({
    text: "原问题",
    contextMode: "continue",
    answerMode: "auto",
    resultMode: "entries",
    basisMode: "knowledge_only",
    sourceRunId: 17,
    random: fixedId,
  });
  const retried = retrySubmissionWithNewId(pending, () => "new-client-id");
  expect(retried.sourceRunId).toBe(17);
  expect(retried.basisMode).toBe("knowledge_only");
});

test("409 冲突标记后不创建第二个本地任务", () => {
  const pending = markConflict(
    attachConversation(
      createPendingSubmission({
        text: "问题",
        contextMode: "auto",
        answerMode: "auto",
        resultMode: "auto",
        basisMode: "auto",
        random: fixedId,
      }),
      9,
    ),
  );
  expect(pending.phase).toBe("conflict");
  expect(canRetrySubmission(pending)).toBe(false);
});
