import { z } from "zod";

export const simEventSchema = z.object({
  event_id: z.string(),
  event_type: z.string(),
  occurred_at: z.string(),
  source: z.enum(["simulator", "twitch"]),
  actor: z.object({ display_name: z.string().nullable() }).nullable(),
  payload: z.record(z.string(), z.unknown()),
});

export const simStatusSchema = z.object({
  running: z.boolean(),
  simulated: z.literal(true),
  generated_events: z.number(),
  last_event_at: z.string().nullable(),
  events: z.array(simEventSchema),
});
