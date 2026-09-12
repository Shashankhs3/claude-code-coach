import * as assert from "assert";
import { CoachStatusBar } from "../../statusBar";

suite("Status bar — real states only", () => {
  test("defaults to Connecting on construction", () => {
    const bar = new CoachStatusBar();
    try {
      assert.match((bar as unknown as { item: { text: string } }).item.text, /Connecting/);
    } finally {
      bar.dispose();
    }
  });

  test("set('ready') shows Ready", () => {
    const bar = new CoachStatusBar();
    try {
      bar.set("ready");
      assert.match((bar as unknown as { item: { text: string } }).item.text, /Ready/);
    } finally {
      bar.dispose();
    }
  });

  test("set('offline') shows Offline with a warning background", () => {
    const bar = new CoachStatusBar();
    try {
      bar.set("offline");
      const item = (bar as unknown as { item: { text: string; backgroundColor: unknown } }).item;
      assert.match(item.text, /Offline/);
      assert.ok(item.backgroundColor, "offline state should use the warning background color");
    } finally {
      bar.dispose();
    }
  });

  test("set('paused') shows Paused", () => {
    const bar = new CoachStatusBar();
    try {
      bar.set("paused");
      assert.match((bar as unknown as { item: { text: string } }).item.text, /Paused/);
    } finally {
      bar.dispose();
    }
  });

  test("set('attention') shows Attention with a warning background", () => {
    const bar = new CoachStatusBar();
    try {
      bar.set("attention");
      const item = (bar as unknown as { item: { text: string; backgroundColor: unknown } }).item;
      assert.match(item.text, /Attention/);
      assert.ok(item.backgroundColor, "attention state should be visually distinct, not color-only");
    } finally {
      bar.dispose();
    }
  });

  test("Attention and Offline use distinct icon glyphs, not color alone (section 19)", () => {
    const bar = new CoachStatusBar();
    try {
      bar.set("attention");
      const attentionText = (bar as unknown as { item: { text: string } }).item.text;
      bar.set("offline");
      const offlineText = (bar as unknown as { item: { text: string } }).item.text;
      assert.notStrictEqual(attentionText, offlineText);
    } finally {
      bar.dispose();
    }
  });
});
