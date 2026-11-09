// Updater check/install flow, kept out of main.js so it can be tested without Electron.
const CHECK_TIMEOUT_MS = 15 * 1000;
const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000;

const MESSAGES = {
  checkUnavailable: "Update checks are available in the installed desktop app.",
  checkLatest: "You are on the latest version.",
  checkNoRelease: "No published release found yet. You are on the latest version.",
  checkFailed: "Could not check for updates. Try again later.",
  unavailable: "Updates are available in the installed desktop app.",
  cancelled: "Update cancelled. Your downloads keep running.",
  empty: "No downloaded update to install. Check for updates again.",
  timeout: "The update download timed out. Check your connection, then retry.",
  failed: "Could not download the update. Try again later.",
  installing: "Restarting to finish the update.",
};

function withTimeout(promise, ms, message) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("timeout")), ms);
    if (typeof timer.unref === "function") timer.unref();
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

function activeJobCount(payload) {
  const jobs = Array.isArray(payload?.jobs)
    ? payload.jobs
    : Array.isArray(payload)
      ? payload
      : [];
  return jobs.filter((job) => job && (job.status === "queued" || job.status === "downloading"))
    .length;
}

async function checkForUpdate({ app, autoUpdater, timeoutMs = CHECK_TIMEOUT_MS }) {
  const currentVersion = app.getVersion();
  if (!app.isPackaged || !autoUpdater) {
    return {
      status: "unavailable",
      version: currentVersion,
      message: MESSAGES.checkUnavailable,
    };
  }
  let timeoutId = null;
  try {
    autoUpdater.autoDownload = false;
    const result = await Promise.race([
      autoUpdater.checkForUpdates(),
      new Promise((_, reject) => {
        timeoutId = setTimeout(
          () => reject(new Error("Update check timed out")),
          timeoutMs
        );
      }),
    ]);
    const latest = result && result.updateInfo && result.updateInfo.version;
    if (latest && latest !== currentVersion) {
      return {
        status: "available",
        version: latest,
        message: `Version ${latest} is available.`,
      };
    }
    return {
      status: "up-to-date",
      version: currentVersion,
      message: MESSAGES.checkLatest,
    };
  } catch (error) {
    const text = String((error && error.message) || error || "");
    if (/404|not found|latest\.yml|no published/i.test(text)) {
      return {
        status: "up-to-date",
        version: currentVersion,
        message: MESSAGES.checkNoRelease,
      };
    }
    return {
      status: "error",
      version: currentVersion,
      message: MESSAGES.checkFailed,
    };
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

async function installUpdate({
  app,
  autoUpdater,
  dialog,
  scheduleQuit = (fn) => setTimeout(fn, 100),
  downloadTimeoutMs = DOWNLOAD_TIMEOUT_MS,
  countActiveJobs = null,
}) {
  if (!app.isPackaged || !autoUpdater) {
    return { status: "unavailable", message: MESSAGES.unavailable };
  }

  const active = countActiveJobs ? await countActiveJobs().catch(() => 0) : 0;
  if (dialog) {
    const detail =
      active > 0
        ? `${active} download${active === 1 ? "" : "s"} still running will stop.`
        : "Any download that starts before the restart will stop.";
    const { response } = await dialog.showMessageBox({
      type: "question",
      buttons: ["Keep working", "Install now"],
      defaultId: 0,
      cancelId: 0,
      title: "Install update",
      message: "Install the update now?",
      detail,
    });
    if (response !== 1) {
      return { status: "cancelled", message: MESSAGES.cancelled };
    }
  }

  try {
    const downloaded = await withTimeout(
      autoUpdater.downloadUpdate(),
      downloadTimeoutMs,
      MESSAGES.timeout
    );
    if (!Array.isArray(downloaded) || downloaded.length === 0) {
      return { status: "error", message: MESSAGES.empty };
    }
    // Let the IPC reply reach the renderer before the window closes.
    scheduleQuit(() => autoUpdater.quitAndInstall(false, true));
    return { status: "installing", message: MESSAGES.installing };
  } catch (error) {
    const timedOut = String(error && error.message) === "timeout";
    return {
      status: "error",
      message: timedOut ? MESSAGES.timeout : MESSAGES.failed,
    };
  }
}

module.exports = {
  checkForUpdate,
  installUpdate,
  withTimeout,
  activeJobCount,
  CHECK_TIMEOUT_MS,
  DOWNLOAD_TIMEOUT_MS,
  MESSAGES,
};
