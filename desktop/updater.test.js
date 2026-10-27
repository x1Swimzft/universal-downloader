const assert = require("node:assert/strict");
const test = require("node:test");

const { installUpdate, withTimeout, activeJobCount, MESSAGES } = require("./updater");

function fakeUpdater(overrides = {}) {
  const calls = { quit: 0 };
  return {
    calls,
    downloadUpdate: async () => ["installer.exe"],
    quitAndInstall: () => {
      calls.quit += 1;
    },
    ...overrides,
  };
}

const packagedApp = { isPackaged: true };
const yesDialog = { showMessageBox: async () => ({ response: 1 }) };
const noDialog = { showMessageBox: async () => ({ response: 0 }) };

test("refuses to install when the app is not packaged", async () => {
  const result = await installUpdate({
    app: { isPackaged: false },
    autoUpdater: fakeUpdater(),
    dialog: yesDialog,
  });
  assert.equal(result.status, "unavailable");
});

test("cancel keeps the app running and downloads nothing", async () => {
  let downloaded = false;
  const autoUpdater = fakeUpdater({
    downloadUpdate: async () => {
      downloaded = true;
      return ["installer.exe"];
    },
  });

  const result = await installUpdate({
    app: packagedApp,
    autoUpdater,
    dialog: noDialog,
    countActiveJobs: async () => 2,
  });

  assert.equal(result.status, "cancelled");
  assert.equal(downloaded, false);
  assert.equal(autoUpdater.calls.quit, 0);
});

test("warns with the number of running downloads", async () => {
  let seen = null;
  const dialog = {
    showMessageBox: async (options) => {
      seen = options;
      return { response: 1 };
    },
  };

  await installUpdate({
    app: packagedApp,
    autoUpdater: fakeUpdater(),
    dialog,
    scheduleQuit: () => {},
    countActiveJobs: async () => 3,
  });

  assert.match(seen.detail, /3 downloads/);
  assert.equal(seen.cancelId, 0);
});

test("replies before quitting so the renderer sees the message", async () => {
  const order = [];
  const autoUpdater = fakeUpdater({
    quitAndInstall: () => order.push("quit"),
  });

  const result = await installUpdate({
    app: packagedApp,
    autoUpdater,
    dialog: yesDialog,
    scheduleQuit: (fn) => order.push("scheduled"),
    countActiveJobs: async () => 0,
  });
  order.push("replied");

  assert.equal(result.status, "installing");
  assert.deepEqual(order, ["scheduled", "replied"]);
  assert.equal(autoUpdater.calls.quit, 0);
});

test("a hung download times out with an actionable message", async () => {
  const autoUpdater = fakeUpdater({
    downloadUpdate: () => new Promise(() => {}),
  });

  const result = await installUpdate({
    app: packagedApp,
    autoUpdater,
    dialog: yesDialog,
    downloadTimeoutMs: 20,
    countActiveJobs: async () => 0,
  });

  assert.equal(result.status, "error");
  assert.equal(result.message, MESSAGES.timeout);
});

test("an empty download result does not quit the app", async () => {
  const autoUpdater = fakeUpdater({ downloadUpdate: async () => [] });

  const result = await installUpdate({
    app: packagedApp,
    autoUpdater,
    dialog: yesDialog,
    scheduleQuit: () => {},
    countActiveJobs: async () => 0,
  });

  assert.equal(result.status, "error");
  assert.equal(result.message, MESSAGES.empty);
  assert.equal(autoUpdater.calls.quit, 0);
});

test("withTimeout rejects and clears its timer", async () => {
  await assert.rejects(() => withTimeout(new Promise(() => {}), 10), /timeout/);
  assert.equal(await withTimeout(Promise.resolve("ok"), 50), "ok");
});

test("activeJobCount counts queued and downloading jobs only", () => {
  assert.equal(activeJobCount({ jobs: [{ status: "queued" }, { status: "done" }] }), 1);
  assert.equal(activeJobCount([{ status: "downloading" }, { status: "downloading" }]), 2);
  assert.equal(activeJobCount(null), 0);
  assert.equal(activeJobCount({ jobs: [] }), 0);
});
