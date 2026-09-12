import * as assert from "assert";
import { CoachingStateStore, DEDUPE_WINDOW_MS } from "../../coachingState";
import { makeFakeMemento } from "./testUtil";

suite("CoachingStateStore — pause/resume", () => {
  test("defaults to not paused", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    assert.strictEqual(store.isPaused(), false);
  });

  test("setPaused(true) persists across reads", async () => {
    const store = new CoachingStateStore(makeFakeMemento());
    await store.setPaused(true);
    assert.strictEqual(store.isPaused(), true);
  });

  test("setPaused(false) resumes", async () => {
    const store = new CoachingStateStore(makeFakeMemento());
    await store.setPaused(true);
    await store.setPaused(false);
    assert.strictEqual(store.isPaused(), false);
  });
});

suite("CoachingStateStore — notification deduplication (15-minute window)", () => {
  test("a signal never notified before is not deduped", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    assert.strictEqual(store.wasRecentlyNotified("C:\\proj", "session-1", "broad_exploration"), false);
  });

  test("same workspace + session + kind, within the window -> deduped", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    const t0 = 1_000_000;
    void store.markNotified("C:\\proj", "session-1", "broad_exploration", t0);
    assert.strictEqual(
      store.wasRecentlyNotified("C:\\proj", "session-1", "broad_exploration", t0 + 60_000),
      true,
    );
  });

  test("same key, after the dedupe window elapses -> allowed again", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    const t0 = 1_000_000;
    void store.markNotified("C:\\proj", "session-1", "broad_exploration", t0);
    assert.strictEqual(
      store.wasRecentlyNotified("C:\\proj", "session-1", "broad_exploration", t0 + DEDUPE_WINDOW_MS + 1),
      false,
    );
  });

  test("a different signal kind in the same session is never suppressed by another kind's dedup entry", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    const t0 = 1_000_000;
    void store.markNotified("C:\\proj", "session-1", "broad_exploration", t0);
    assert.strictEqual(store.wasRecentlyNotified("C:\\proj", "session-1", "context_noisy", t0 + 1), false);
  });

  test("a different session is never suppressed by another session's dedup entry", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    const t0 = 1_000_000;
    void store.markNotified("C:\\proj", "session-1", "broad_exploration", t0);
    assert.strictEqual(store.wasRecentlyNotified("C:\\proj", "session-2", "broad_exploration", t0 + 1), false);
  });

  test("a different workspace is never suppressed by another workspace's dedup entry", () => {
    const store = new CoachingStateStore(makeFakeMemento());
    const t0 = 1_000_000;
    void store.markNotified("C:\\proj-a", "session-1", "broad_exploration", t0);
    assert.strictEqual(
      store.wasRecentlyNotified("C:\\proj-b", "session-1", "broad_exploration", t0 + 1),
      false,
    );
  });
});
