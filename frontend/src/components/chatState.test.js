import assert from "node:assert/strict";
import test from "node:test";

import { boundedHistory, chatContextKey, createRequestGate } from "./chatState.js";

const turn = (role, text) => ({ role, content: [{ text }] });

test("context changes invalidate and abort an in-flight request", () => {
  const gate = createRequestGate();
  const oldKey = chatContextKey("P-1", { crews_available: 20 }, {}, null);
  const token = gate.begin(oldKey);
  assert.ok(token && gate.isCurrent(token, oldKey));

  gate.invalidate();
  const newKey = chatContextKey("P-2", { crews_available: 40 }, {}, null);
  assert.equal(token.signal.aborted, true);
  assert.equal(gate.isCurrent(token, newKey), false);
});

test("the synchronous request gate prevents rapid double submissions", () => {
  const gate = createRequestGate();
  const token = gate.begin("context");
  assert.ok(token);
  assert.equal(gate.begin("context"), null);
  assert.equal(gate.finish(token), true);
  assert.ok(gate.begin("context")); // retry/new submission works after the prior request finishes
});

test("bounded history retains alternating pairs below backend limits", () => {
  const history = [];
  for (let i = 0; i < 15; i += 1) {
    history.push(turn("user", `question ${i}`), turn("assistant", `answer ${i}`));
  }
  const next = boundedHistory(history, "new question");
  assert.ok(next.length <= 19);
  assert.equal(next[0].role, "user");
  assert.equal(next.at(-1).role, "user");
  assert.ok(next.every((message, i) => i === 0 || message.role !== next[i - 1].role));
});

test("utility confirmation is part of the request context", () => {
  const base = chatContextKey("P-1", {}, {}, null);
  const simulated = chatContextKey("P-1", {}, {}, { outage_confirmed: true });
  assert.notEqual(base, simulated);
});

test("scenario and profile changes produce new request contexts", () => {
  const base = chatContextKey("P-1", { crews_available: 20 }, { alerts_enrolled: false }, null);
  const scenario = chatContextKey("P-1", { crews_available: 30 }, { alerts_enrolled: false }, null);
  const profile = chatContextKey("P-1", { crews_available: 20 }, { alerts_enrolled: true }, null);
  assert.notEqual(base, scenario);
  assert.notEqual(base, profile);
});
