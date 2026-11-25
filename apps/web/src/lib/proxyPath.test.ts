import assert from "node:assert/strict";
import { test } from "node:test";
import { isBlockedProxyPath } from "./proxyPath.ts";

test("sign in and webhooks are never forwarded, however the path is written", () => {
  for (const path of [["auth", "login"], ["auth", "login", ""], ["webhooks", "email"], ["Auth", "Login"], [".", "auth", "login"], ["%2e", "auth", "login"], ["%2E%2E", "auth", "login"],
    ["x", "..", "auth", "login"], ["x", "%2e%2e", "webhooks", "form"], ["auth%2Flogin"], ["auth", "%2e", "login"], ["a", ".", "..", "webhooks"], ["auth\\login"], ["%zz"]]) {
    assert.equal(isBlockedProxyPath(path), true, JSON.stringify(path));
  }
});

test("ordinary calls still go through", () => {
  for (const path of [["overview"], ["leads", "12"], ["inbox", "unmatched"], ["auth", "me"], ["auth", "logout"], ["approvals", "3", "decide"], ["x", "..", "overview"]]) {
    assert.equal(isBlockedProxyPath(path), false, JSON.stringify(path));
  }
});
