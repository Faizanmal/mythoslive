import test from "node:test";
import assert from "node:assert/strict";
import { simStatusSchema } from "../src/lib/simulator-contract.mjs";

test("simulator contract requires explicit simulation label", () => {
  const result = simStatusSchema.safeParse({
    running: false, simulated: true, generated_events: 1,
    last_event_at: null,
    events: [{ event_id: "evt-1", event_type: "chat.command.join",
      occurred_at: "2026-11-02T00:00:00Z", source: "simulator",
      actor: { display_name: "[SIM] Ashrunner" }, payload: {} }],
  });
  assert.equal(result.success, true);
});

test("simulator contract rejects unlabeled or unsupported event sources", () => {
  assert.equal(simStatusSchema.safeParse({ running: false, generated_events: 0,
    last_event_at: null, events: [] }).success, false);
  assert.equal(simStatusSchema.safeParse({ running: false, simulated: true,
    generated_events: 0, last_event_at: null,
    events: [{ event_id: "evt-1", event_type: "chat", occurred_at: "now",
      source: "unknown", actor: null, payload: {} }] }).success, false);
});
