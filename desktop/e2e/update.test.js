const assert = require("node:assert/strict");
const http = require("node:http");
const test = require("node:test");

const { checkForUpdate, installUpdate } = require("../updater");

const app = { isPackaged: true, getVersion: () => "1.0.0" };
const yesDialog = { showMessageBox: async () => ({ response: 1 }) };

function startFeed(version, status = 200) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      if (req.url.startsWith("/latest.yml") && status === 200) {
        res.writeHead(200, { "content-type": "text/yaml" });
        res.end(`version: ${version}\nfiles: []\n`);
        return;
      }
      res.writeHead(status === 200 ? 404 : status);
      res.end("not found");
    });
    server.listen(0, "127.0.0.1", () => {
      resolve({
        server,
        url: `http://127.0.0.1:${server.address().port}/`,
      });
    });
  });
}

function closeFeed(server) {
  return new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  });
}

function feedUpdater(url, calls) {
  return {
    autoDownload: true,
    async checkForUpdates() {
      const response = await fetch(`${url}latest.yml`);
      if (!response.ok) throw new Error(`latest.yml ${response.status}`);
      const text = await response.text();
      calls.push("check");
      return { updateInfo: { version: /^version:\s*(\S+)/m.exec(text)[1] } };
    },
    async downloadUpdate() {
      calls.push("download");
      return ["installer.exe"];
    },
    quitAndInstall() {
      calls.push("relaunch");
    },
  };
}

test("local feed: check -> available -> download -> install -> relaunch", async (t) => {
  const { server, url } = await startFeed("9.9.9");
  t.after(() => closeFeed(server));

  const calls = [];
  const autoUpdater = feedUpdater(url, calls);

  const check = await checkForUpdate({ app, autoUpdater });
  assert.deepEqual(check, {
    status: "available",
    version: "9.9.9",
    message: "Version 9.9.9 is available.",
  });
  assert.equal(autoUpdater.autoDownload, false);

  const install = await installUpdate({
    app,
    autoUpdater,
    dialog: yesDialog,
    scheduleQuit: (fn) => fn(),
    countActiveJobs: async () => 0,
  });

  assert.equal(install.status, "installing");
  assert.deepEqual(calls, ["check", "download", "relaunch"]);
});

test("local feed: matching version is up-to-date and never installs", async (t) => {
  const { server, url } = await startFeed("1.0.0");
  t.after(() => closeFeed(server));

  const calls = [];
  const autoUpdater = feedUpdater(url, calls);

  const check = await checkForUpdate({ app, autoUpdater });
  assert.equal(check.status, "up-to-date");
  assert.equal(check.version, "1.0.0");
  assert.deepEqual(calls, ["check"]);
});

test("local feed: 404 is reported as up-to-date", async (t) => {
  const { server, url } = await startFeed("1.0.0", 404);
  t.after(() => closeFeed(server));

  const autoUpdater = feedUpdater(url, []);
  const check = await checkForUpdate({ app, autoUpdater });

  assert.equal(check.status, "up-to-date");
  assert.match(check.message, /No published release/);
});

test("network and download failures do not quit the app", async () => {
  const networkFailure = {
    checkForUpdates: async () => {
      throw new Error("ECONNREFUSED");
    },
  };
  assert.equal((await checkForUpdate({ app, autoUpdater: networkFailure })).status, "error");

  let quit = false;
  const downloadFailure = {
    checkForUpdates: async () => ({ updateInfo: { version: "9.9.9" } }),
    downloadUpdate: async () => {
      throw new Error("download failed");
    },
    quitAndInstall: () => {
      quit = true;
    },
  };
  const install = await installUpdate({
    app,
    autoUpdater: downloadFailure,
    dialog: yesDialog,
    scheduleQuit: (fn) => fn(),
    countActiveJobs: async () => 0,
  });

  assert.equal(install.status, "error");
  assert.equal(quit, false);
});
