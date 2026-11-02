import { z } from "zod";
export const simEventSchema: z.ZodType<{
  event_id: string; event_type: string; occurred_at: string;
  source: "simulator" | "twitch";
  actor: { display_name: string | null } | null;
  payload: Record<string, unknown>;
}>;
export const simStatusSchema: z.ZodType<{
  running: boolean; simulated: true; generated_events: number;
  last_event_at: string | null;
  events: Array<{
    event_id: string; event_type: string; occurred_at: string;
    source: "simulator" | "twitch";
    actor: { display_name: string | null } | null;
    payload: Record<string, unknown>;
  }>;
}>;
