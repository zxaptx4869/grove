import { apiConfigured } from "@/src/api";
test("不以 localhost 作为默认 API 地址", () => { expect(apiConfigured).toBe(false); });
