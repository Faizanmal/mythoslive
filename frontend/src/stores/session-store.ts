import { create } from "zustand";

type SessionStore = {
  connection: "disconnected" | "connecting" | "connected";
  setConnection: (connection: SessionStore["connection"]) => void;
};

export const useSessionStore = create<SessionStore>((set) => ({
  connection: "disconnected",
  setConnection: (connection) => set({ connection }),
}));
