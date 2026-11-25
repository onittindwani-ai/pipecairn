import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeProxyPath, isBlockedProxyPath } from "./proxyPath.ts";

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

test("a segment that would change where the path ends is refused, not forwarded", () => {
  for (const path of [["auth", "login%3F"], ["auth", "login%3f"], ["auth", "login%23"], ["auth", "login%00"], ["auth", "login%0d%0a"], ["auth", "login%25"], ["overview%3Fx=1"], ["a%23b"], ["auth", "login%7F"]]) {
    assert.equal(isBlockedProxyPath(path), true, JSON.stringify(path));
    assert.equal(encodeProxyPath(path), null, JSON.stringify(path));
  }
});

test("what is forwarded is the checked path with every segment encoded again", () => {
  assert.equal(encodeProxyPath(["inbox", "unmatched", "12"]), "inbox/unmatched/12");
  assert.equal(encodeProxyPath(["x", "..", "overview"]), "overview");
  assert.equal(encodeProxyPath(["a%20b", "c"]), "a%20b/c");
  assert.equal(encodeProxyPath(["caf%C3%A9"]), "caf%C3%A9");
});
