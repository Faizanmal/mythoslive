"use client";

import { useEffect, useRef } from "react";
import type { EngineRealtimeEvent } from "@/lib/contracts.generated";

export type OverlayState = Record<string, unknown>;
export type KenneyManifest = {
  tileSheet?: string; tileFrameWidth?: number; tileFrameHeight?: number; floorFrame?: number;
  heroSheet?: string; heroFrameWidth?: number; heroFrameHeight?: number; heroFrame?: number;
};

export function PhaserStage({
  state,
  latestEvent,
  layout,
  assetManifest,
  onDiagnostics,
}: {
  state: OverlayState | null;
  latestEvent: EngineRealtimeEvent | null;
  layout: "bottom" | "right" | "full";
  assetManifest: KenneyManifest | null;
  onDiagnostics?: (fps: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<import("phaser").Game | null>(null);
  const latest = useRef({ state, latestEvent, layout });
  const lastFxEvent = useRef<string | null>(null);
  const hitStopTimer = useRef<number | null>(null);
  latest.current = { state, latestEvent, layout };

  useEffect(() => {
    let cancelled = false;
    document.documentElement.classList.add("overlay-transparent");

    void import("phaser").then(({ default: Phaser }) => {
      if (cancelled || !host.current) return;

      class EmberfallScene extends Phaser.Scene {
        private terrain?: Phaser.GameObjects.Graphics;
        private actors = new Map<string, Phaser.GameObjects.Container>();
        private damagePool: Phaser.GameObjects.Text[] = [];
        private tileArt?: Phaser.GameObjects.Container;
        private presentation: OverlayState | null = null;
        private lastLayout = "bottom";
        private lastMode = "";
        private lastHeroesSignature = "";
        private lastTorchCount = -1;
        private lastFpsAt = 0;
        private readonly sceneKey: string;

        constructor(key = "world") { super(key); this.sceneKey = key; }

        create() {
          this.terrain = this.add.graphics().setDepth(2);
          this.tileArt = this.add.container(0, 0).setDepth(1);
          this.drawWorld();
          this.damagePool = Array.from({ length: 18 }, () => {
            const text = this.add.text(0, 0, "", {
              fontFamily: "Georgia, serif", fontSize: "27px", color: "#ffe08c",
              stroke: "#211708", strokeThickness: 5, fontStyle: "bold",
            }).setDepth(15).setVisible(false);
            return text;
          });
          this.scale.on("resize", () => this.drawWorld());
          this.game.events.on("mythos:present", (next: OverlayState | null, nextLayout: string) => {
            this.present(next, nextLayout);
          });
          this.game.events.emit("mythos:present", latest.current.state, latest.current.layout);
          this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
            this.scale.off("resize");
            this.game.events.off("mythos:present");
            this.actors.clear();
          });
        }

        present(next: OverlayState | null, nextLayout: string) {
          this.presentation = next;
          const nextMode = String(next?.state ?? "LOBBY");
          const targetScene = nextMode === "BOSS" ? "boss" : nextMode === "RECAP" || nextMode === "ENDED" ? "chronicle" : "world";
          if (this.sceneKey !== targetScene) {
            this.scene.start(targetScene);
            return;
          }
          if (this.lastMode !== nextMode) {
            this.lastMode = nextMode;
            this.drawWorld();
          }
          const torchCount = Math.max(0, Math.min(12, Number(next?.torches_lit ?? 0)));
          if (torchCount !== this.lastTorchCount) {
            this.lastTorchCount = torchCount;
            this.drawWorld();
          }
          if (this.lastLayout !== nextLayout) {
            this.lastLayout = nextLayout;
            this.drawWorld();
          }
          const heroes = Array.isArray(next?.heroes) ? next.heroes.slice(0, 40) as Record<string, unknown>[] : [];
          const heroSignature = JSON.stringify(heroes.map(({ display_name, class_name, level, hp, max_hp, downed, ghost }) => ({ display_name, class_name, level, hp, max_hp, downed, ghost })));
          if (heroSignature === this.lastHeroesSignature) return;
          this.lastHeroesSignature = heroSignature;
          const activeNames = new Set<string>();
          heroes.forEach((hero, index) => {
            const name = String(hero.display_name ?? `Adventurer ${index + 1}`);
            activeNames.add(name);
            const twitchColor = typeof hero.chat_color === "string" && /^#[0-9a-f]{6}$/i.test(hero.chat_color) ? hero.chat_color : null;
            let actor = this.actors.get(name);
            if (!actor) {
              actor = this.makeHero(name, index, twitchColor ? Number.parseInt(twitchColor.slice(1), 16) : undefined);
              this.actors.set(name, actor);
              actor.setAlpha(0).setY(actor.y + 24);
              this.tweens.add({ targets: actor, alpha: 1, y: actor.y - 24, duration: 460, ease: "Back.Out" });
            }
            const x = this.heroX(index, heroes.length);
            const y = 628 + (index % 3) * 22;
            this.tweens.add({ targets: actor, x, y, duration: 420, ease: "Sine.Out" });
            const badge = actor.getData("nameplate") as Phaser.GameObjects.Text | undefined;
            const className = String(hero.class_name ?? "wayfarer").toUpperCase();
            badge?.setText(`${name}\n${className} · Lv ${String(hero.level ?? 1)}`);
            if (twitchColor) badge?.setColor(twitchColor);
            const ghost = Boolean(hero.ghost || hero.downed);
            actor.setAlpha(ghost ? 0.5 : 1);
            actor.setData("bodyColor", this.chatColor(name));
          });
          for (const [name, actor] of this.actors) {
            if (!activeNames.has(name)) {
              this.tweens.add({ targets: actor, alpha: 0, duration: 240, onComplete: () => { actor.destroy(); this.actors.delete(name); } });
            }
          }
        }

        private makeHero(name: string, index: number, twitchColor?: number) {
          const container = this.add.container(this.heroX(index, 1), 638).setDepth(10);
          const color = twitchColor ?? this.chatColor(name);
          const shadow = this.add.ellipse(0, 16, 45, 13, 0x080a0c, 0.65);
          const art: Phaser.GameObjects.GameObject[] = [shadow];
          if (this.textures.exists("kenney-heroes")) {
            const heroSprite = this.add.image(0, 0, "kenney-heroes", assetManifest?.heroFrame ?? 0).setDisplaySize(33, 48);
            art.push(heroSprite);
          } else {
            art.push(
              this.add.ellipse(0, 0, 30, 42, color, 1).setStrokeStyle(2, 0xf2d08b, 0.95),
              this.add.circle(0, -18, 12, 0xffd6a3).setStrokeStyle(2, 0x593926, 1),
              this.add.arc(0, -20, 13, 205, 335, false, 0x493c65).setStrokeStyle(5, 0x493c65, 1),
            );
          }
          const label = this.add.text(0, 35, "", {
            fontFamily: "Arial, sans-serif", fontSize: "13px", color: "#fff8df",
            align: "center", lineSpacing: 1, stroke: "#111014", strokeThickness: 4,
            backgroundColor: "#171a20cc", padding: { left: 7, right: 7, top: 4, bottom: 4 },
          }).setOrigin(0.5, 0).setDepth(12);
          container.add([...art, label]);
          container.setData("nameplate", label);
          container.setData("index", index);
          return container;
        }

        private drawWorld() {
          if (!this.terrain) return;
          const g = this.terrain;
          const w = this.scale.width;
          const h = this.scale.height;
          g.clear();
          this.tileArt?.removeAll(true);
          const narrow = this.lastLayout === "right";
          const left = narrow ? w * 0.08 : w * 0.19;
          const width = narrow ? w * 0.84 : w * 0.62;
          const top = narrow ? h * 0.29 : h * 0.24;
          const groundY = narrow ? h * 0.74 : h * 0.69;
          // Empty transparent canvas with a softly framed, handcrafted tile-scape.
          g.fillStyle(0x1b1b27, 0.12).fillRoundedRect(left - 25, top - 22, width + 50, groundY - top + 92, 34);
          g.lineStyle(2, 0xd7b570, 0.38).strokeRoundedRect(left - 25, top - 22, width + 50, groundY - top + 92, 34);
          for (let row = 0; row < 5; row++) {
            for (let col = 0; col < 18; col++) {
              const x = left + col * width / 18;
              const y = top + row * (groundY - top) / 5;
              const tw = width / 18;
              const th = (groundY - top) / 5;
              const colors = [0x2e3640, 0x343c43, 0x3a3d46, 0x424144];
              g.fillStyle(colors[(row * 13 + col * 7) % colors.length], 0.48);
              g.fillRoundedRect(x + 2, y + 2, tw - 4, th - 4, 5);
              if (this.textures.exists("kenney-tiles") && this.tileArt) {
                this.tileArt.add(this.add.image(x + tw / 2, y + th / 2, "kenney-tiles", assetManifest?.floorFrame ?? 0).setDisplaySize(tw - 3, th - 3).setAlpha(0.82));
              }
              if ((row * 7 + col) % 9 === 0) {
                g.fillStyle(0xe9ad5b, 0.38).fillCircle(x + tw * 0.75, y + th * 0.28, 3);
              }
            }
          }
          g.fillStyle(0x171e20, 0.78).fillRoundedRect(left, groundY - 5, width, 20, 8);
          // Lantern-lit town silhouettes and distant mountain shapes.
          const skylineY = top + 52;
          for (let i = 0; i < 7; i++) {
            const x = left + 35 + i * (width - 70) / 6;
            const bh = 35 + (i * 19) % 52;
            g.fillStyle(i % 2 ? 0x343243 : 0x39404a, 0.82).fillRoundedRect(x - 18, skylineY - bh, 38, bh, 4);
            g.fillStyle(0x6c4f49, 0.95).fillTriangle(x - 24, skylineY - bh + 4, x, skylineY - bh - 21, x + 24, skylineY - bh + 4);
            g.fillStyle(0xf2bd64, 0.75).fillCircle(x, skylineY - 12, 4);
          }
          const torches = Math.max(0, Math.min(12, Number(this.presentation?.torches_lit ?? 0)));
          for (let i = 0; i < torches; i++) {
            const x = left + width * (0.08 + 0.84 * (i % 6) / 5);
            const y = groundY - 19 - Math.floor(i / 6) * 28;
            g.lineStyle(4, 0x76513a, 0.95).lineBetween(x, y, x, y + 21);
            g.fillStyle(0xf7b74e, 0.32).fillCircle(x, y - 4, 12);
            g.fillStyle(0xffd988, 0.95).fillTriangle(x, y - 12, x - 5, y - 2, x + 5, y - 2);
          }
          if (String(this.presentation?.state) === "BOSS") {
            const cx = w / 2;
            const cy = top + (groundY - top) * 0.62;
            g.fillStyle(0x17141b, 0.72).fillEllipse(cx, cy + 100, 285, 52);
            g.fillStyle(0x843c36, 0.96).fillCircle(cx, cy, 92).fillEllipse(cx, cy + 82, 172, 112);
            g.fillStyle(0x4c3438, 1).fillTriangle(cx - 58, cy - 54, cx - 100, cy - 156, cx - 12, cy - 76);
            g.fillTriangle(cx + 58, cy - 54, cx + 100, cy - 156, cx + 12, cy - 76);
            g.fillStyle(0xffd887, 0.95).fillCircle(cx - 32, cy - 2, 11).fillCircle(cx + 32, cy - 2, 11);
            g.fillStyle(0x17141b, 0.95).fillCircle(cx - 32, cy - 2, 4).fillCircle(cx + 32, cy - 2, 4);
            g.lineStyle(2, 0xf0ba79, 0.7).strokeCircle(cx, cy, 112);
          }
          if (String(this.presentation?.state) === "RECAP" || String(this.presentation?.state) === "ENDED") {
            g.fillStyle(0xead8b4, 0.93).fillRoundedRect(w * 0.3, h * 0.24, w * 0.4, h * 0.43, 18);
            g.lineStyle(3, 0xa78250, 0.9).strokeRoundedRect(w * 0.3, h * 0.24, w * 0.4, h * 0.43, 18);
            g.fillStyle(0x9e663b, 0.7).fillCircle(w / 2, h * 0.28, 18);
          }
          const title = String(this.presentation?.scene && (this.presentation.scene as Record<string, unknown>).title || "EMBERFALL · THE LANTERN ROAD");
          if (this.scene.isActive()) {
            const label = this.children.getByName("location-label") as Phaser.GameObjects.Text | null;
            if (label) label.setText(title.toUpperCase());
            else this.add.text(w / 2, top - 8, title.toUpperCase(), {
              fontFamily: "Georgia, serif", fontSize: "20px", color: "#f8d88c", letterSpacing: 3,
              stroke: "#111014", strokeThickness: 5,
            }).setOrigin(0.5, 1).setDepth(4).setName("location-label");
          }
        }

        private heroX(index: number, count: number) {
          const w = this.scale.width;
          const width = this.lastLayout === "right" ? w * 0.77 : w * 0.55;
          const start = (w - width) / 2;
          return start + width * (index + 0.5) / Math.max(1, count);
        }

        private chatColor(value: string) {
          let hash = 0;
          for (let i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) | 0;
          return [0x4b8b7b, 0x7660a3, 0xb06456, 0x477da0, 0xa17a42, 0x68834b][Math.abs(hash) % 6];
        }

        floatDamage(amount: number, source: string) {
          const text = this.damagePool.find((entry) => !entry.visible);
          if (!text) return;
          text.setText(`-${amount}`).setPosition(this.scale.width * 0.5 + Phaser.Math.Between(-65, 65), this.scale.height * 0.43).setAlpha(1).setVisible(true);
          this.tweens.add({ targets: text, y: text.y - 75, alpha: 0, duration: 850, onComplete: () => text.setVisible(false) });
          const shake = this.presentation?.state === "BOSS" ? 0.003 : 0.001;
          this.cameras.main.shake(90, shake);
          void source;
        }

        update(time: number, delta: number) {
          if (time - this.lastFpsAt < 1000) return;
          this.lastFpsAt = time;
          const fps = Math.round(1000 / Math.max(1, delta));
          onDiagnostics?.(fps);
        }
      }

      class BootScene extends Phaser.Scene {
        constructor() { super("boot"); }
        preload() {
          const local = (path?: string) => path && path.startsWith("/assets/kenney/") ? path : null;
          const tileUrl = local(assetManifest?.tileSheet);
          if (tileUrl && assetManifest?.tileFrameWidth && assetManifest?.tileFrameHeight) {
            this.load.spritesheet("kenney-tiles", tileUrl, { frameWidth: assetManifest.tileFrameWidth, frameHeight: assetManifest.tileFrameHeight });
          }
          const heroUrl = local(assetManifest?.heroSheet);
          if (heroUrl && assetManifest?.heroFrameWidth && assetManifest?.heroFrameHeight) {
            this.load.spritesheet("kenney-heroes", heroUrl, { frameWidth: assetManifest.heroFrameWidth, frameHeight: assetManifest.heroFrameHeight });
          }
        }
        create() { this.scene.start("world"); }
      }
      class WorldScene extends EmberfallScene { constructor() { super("world"); } }
      class BossScene extends EmberfallScene { constructor() { super("boss"); } }
      class ChronicleScene extends EmberfallScene { constructor() { super("chronicle"); } }

      const worldScene = new WorldScene();
      game.current = new Phaser.Game({
        type: Phaser.AUTO,
        parent: host.current,
        width: 1920,
        height: 1080,
        transparent: true,
        backgroundColor: "rgba(0,0,0,0)",
        scene: [BootScene, worldScene, new BossScene(), new ChronicleScene()],
        scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
        render: { antialias: true, transparent: true, pixelArt: false, powerPreference: "high-performance" },
        fps: { target: 30, forceSetTimeOut: true },
      });
      const publish = () => game.current?.events.emit("mythos:present", latest.current.state, latest.current.layout);
      game.current.events.once("ready", publish);
    });

    return () => {
      cancelled = true;
      game.current?.destroy(true);
      game.current = null;
      document.documentElement.classList.remove("overlay-transparent");
    };
  }, [onDiagnostics, assetManifest]);

  useEffect(() => {
    if (!game.current) return;
    game.current.events.emit("mythos:present", state, layout);
    if ((latestEvent?.event_type === "damage" || latestEvent?.event_type === "combat_tick") && latestEvent.event_id !== lastFxEvent.current) {
      lastFxEvent.current = latestEvent.event_id;
      const sceneName = state?.state === "BOSS" ? "boss" : "world";
      const scene = game.current.scene.getScene(sceneName) as unknown as {
        floatDamage?: (amount: number, source: string) => void;
        time?: { timeScale: number };
        cameras?: { main: { flash: (duration: number, r: number, g: number, b: number, force: boolean) => void; shake: (duration: number, intensity: number) => void } };
      };
      if (latestEvent.event_type === "damage") {
        scene.floatDamage?.(Number(latestEvent.payload.amount ?? 0), String(latestEvent.payload.source ?? ""));
        if (latestEvent.payload.critical === true) {
          scene.time && (scene.time.timeScale = 0.08);
          scene.cameras?.main.flash(90, 255, 226, 160, false);
          scene.cameras?.main.shake(130, 0.005);
          if (hitStopTimer.current !== null) window.clearTimeout(hitStopTimer.current);
          hitStopTimer.current = window.setTimeout(() => {
            if (scene.time) scene.time.timeScale = 1;
            hitStopTimer.current = null;
          }, 85);
        }
      } else if (Array.isArray(latestEvent.payload.targets)) {
        for (const target of latestEvent.payload.targets as Record<string, unknown>[]) {
          scene.floatDamage?.(Number(target.damage ?? 0), String(target.name ?? ""));
        }
      }
    }
  }, [state, latestEvent, layout]);

  useEffect(() => () => {
    if (hitStopTimer.current !== null) window.clearTimeout(hitStopTimer.current);
    hitStopTimer.current = null;
  }, []);

  return <div aria-label="MythosLive Emberfall game scene" className="overlay-canvas" ref={host} />;
}
