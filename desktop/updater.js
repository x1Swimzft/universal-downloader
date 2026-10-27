// Updater install flow, kept out of main.js so it can be unit-tested without Electron.
const DOWNLOAD_TIMEOUT_MS = 10 * 60 * 1000;

const MESSAGES = {
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

module.exports = { installUpdate, withTimeout, activeJobCount, DOWNLOAD_TIMEOUT_MS, MESSAGES };
