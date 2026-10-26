const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  clipboard,
  nativeImage,
  ipcMain,
  dialog,
  shell,
  Notification,
} = require("electron");
const { spawn, execSync } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const net = require("net");
const http = require("http");
const fs = require("fs");

const appSessionToken = crypto.randomBytes(32).toString("hex");

const ROOT_DIR = path.resolve(__dirname, "..");
const BACKEND_DIR = path.join(ROOT_DIR, "backend");
const FRONTEND_DIR = path.join(ROOT_DIR, "frontend");

// Resolve paths for portable/packaged execution vs local dev execution
function resolveAssetPath(relPath) {
  const inResources = path.join(process.resourcesPath || "", relPath);
  if (fs.existsSync(inResources)) return inResources;
  const inDir = path.join(__dirname, relPath);
  if (fs.existsSync(inDir)) return inDir;
  return null;
}

// 1. Resolve FFmpeg
const bundledBin = resolveAssetPath("bin");
const FFMPEG_BIN =
  bundledBin ||
  "C:\\Users\\Dataria\\Downloads\\ffmpeg-2026-10-01-git-0b01ed76aa-essentials_build\\bin";

// 2. Resolve Backend Executable
const bundledBackend = resolveAssetPath(path.join("backend-engine", "backend-engine.exe"));
const PYTHON_EXE = bundledBackend || path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe");

// 3. Resolve Static Frontend
const bundledFrontend = resolveAssetPath("frontend-out");

// 4. Resolve App Icon
const APP_ICON_PATH =
  resolveAssetPath(path.join("assets", "icon.ico")) ||
  resolveAssetPath(path.join("build", "icon.ico")) ||
  path.join(__dirname, "assets", "icon.ico");

// ไอคอน 16x16 สีฟ้าคราม (Base64 PNG) ป้องกัน Tray ล่องหนบน Windows 11
const TRAY_ICON_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAySURBVDhPY/hPBAwUACYoTTYYNWDUgFEDRg0YNWDUgFEDRg1gIAtA00A1A0g1gIEBAJ8fH/H1461bAAAAAElFTkSuQmCC";

let mainWindow = null;
let tray = null;
let backendProc = null;
let frontendProc = null;
let staticServer = null;
let activeBackendPort = null;
let isQuitting = false;
let lastClipboardText = "";
let settings = null;

function getSettingsPath() {
  return path.join(app.getPath("userData"), "settings.json");
}

function getDefaultSettings() {
  return {
    autoDetectClipboard: true,
    minimizeToTray: true,
    notifyWhenFinished: true,
    maxConcurrent: 3,
    saveFolder: path.join(app.getPath("downloads"), "Universal Downloader"),
    theme: "dark",
  };
}

function loadSettings() {
  const defaults = getDefaultSettings();
  const file = getSettingsPath();
  try {
    if (fs.existsSync(file)) {
      const parsed = JSON.parse(fs.readFileSync(file, "utf-8"));
      settings = {
        autoDetectClipboard:
          typeof parsed.autoDetectClipboard === "boolean"
            ? parsed.autoDetectClipboard
            : defaults.autoDetectClipboard,
        minimizeToTray:
          typeof parsed.minimizeToTray === "boolean"
            ? parsed.minimizeToTray
            : defaults.minimizeToTray,
        notifyWhenFinished:
          typeof parsed.notifyWhenFinished === "boolean"
            ? parsed.notifyWhenFinished
            : defaults.notifyWhenFinished,
        maxConcurrent: [1, 2, 3, 5].includes(Number(parsed.maxConcurrent))
          ? Number(parsed.maxConcurrent)
          : defaults.maxConcurrent,
        saveFolder:
          typeof parsed.saveFolder === "string" && path.isAbsolute(parsed.saveFolder)
            ? parsed.saveFolder
            : defaults.saveFolder,
        theme: parsed.theme === "light" ? "light" : "dark",
      };
    } else {
      settings = defaults;
      persistSettings();
    }
  } catch (_) {
    settings = defaults;
  }
  return settings;
}

function persistSettings() {
  try {
    const file = getSettingsPath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(settings, null, 2), "utf-8");
  } catch (_) {}
}

function syncSettingsToBackend() {
  if (!activeBackendPort || !settings) return;
  const payload = JSON.stringify({
    max_concurrent: settings.maxConcurrent,
    save_folder: settings.saveFolder,
  });
  const req = http.request(
    {
      hostname: "127.0.0.1",
      port: activeBackendPort,
      path: "/api/settings",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
        "X-App-Token": appSessionToken,
      },
    },
    (res) => {
      res.resume();
    }
  );
  req.on("error", () => {});
  req.write(payload);
  req.end();
}

function isWithinAllowedFolder(targetPath, allowedRoot) {
  try {
    fs.mkdirSync(allowedRoot, { recursive: true });
    const realRoot = fs.realpathSync(allowedRoot).toLowerCase();
    const realTarget = fs.realpathSync(targetPath).toLowerCase();
    return (
      realTarget === realRoot ||
      realTarget.startsWith(realRoot.endsWith(path.sep) ? realRoot : realRoot + path.sep)
    );
  } catch (_) {
    return false;
  }
}

const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function findFreePort(start, end) {
  return new Promise((resolve, reject) => {
    const tryPort = (port) => {
      if (port > end) return reject(new Error(`No free port in ${start}-${end}`));
      const srv = net.createServer();
      srv.unref();
      srv.on("error", () => tryPort(port + 1));
      srv.listen(port, "127.0.0.1", () => {
        srv.close(() => resolve(port));
      });
    };
    tryPort(start);
  });
}

function waitForServer(url, timeoutMs = 25000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      http
        .get(url, (res) => {
          if (res.statusCode < 500) return resolve(true);
          retry();
        })
        .on("error", retry);
    };
    const retry = () => {
      if (Date.now() - start > timeoutMs) return resolve(false);
      setTimeout(check, 400);
    };
    check();
  });
}

function killProcessTree(proc) {
  if (!proc || !proc.pid) return;
  try {
    execSync(`taskkill /PID ${proc.pid} /T /F`, { stdio: "ignore", windowsHide: true });
  } catch (_) {}
}

function cleanupChildProcesses() {
  killProcessTree(backendProc);
  backendProc = null;
  killProcessTree(frontendProc);
  frontendProc = null;
  if (staticServer) {
    try {
      staticServer.close();
    } catch (_) {}
    staticServer = null;
  }
}

function serveStaticFolder(folderPath, port) {
  const mimeTypes = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
  };

  const server = http.createServer((req, res) => {
    try {
      const parsedUrl = new URL(req.url, `http://127.0.0.1:${port}`);
      let pathname = parsedUrl.pathname;
      if (pathname === "/") pathname = "/index.html";

      let filePath = path.join(folderPath, pathname);
      if (!fs.existsSync(filePath)) {
        if (fs.existsSync(filePath + ".html")) {
          filePath += ".html";
        } else {
          filePath = path.join(folderPath, "index.html");
        }
      }

      const ext = path.extname(filePath).toLowerCase();
      const contentType = mimeTypes[ext] || "application/octet-stream";

      fs.readFile(filePath, (err, content) => {
        if (err) {
          res.writeHead(500);
          res.end("Error loading file");
        } else {
          res.writeHead(200, { "Content-Type": contentType });
          res.end(content);
        }
      });
    } catch (_) {
      res.writeHead(500);
      res.end("Internal Server Error");
    }
  });

  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

async function startServices() {
  const backendPort = await findFreePort(8000, 8010);
  const frontendPort = await findFreePort(3000, 3010);
  activeBackendPort = backendPort;

  const envWithFfmpeg = {
    ...process.env,
    PATH: `${FFMPEG_BIN};${process.env.PATH || ""}`,
    NEXT_PUBLIC_API_URL: `http://127.0.0.1:${backendPort}/api`,
    PORT: String(frontendPort),
    BACKEND_PORT: String(backendPort),
    FRONTEND_PORT: String(frontendPort),
    FRONTEND_ORIGIN: `http://127.0.0.1:${frontendPort},http://localhost:${frontendPort}`,
    APP_SESSION_TOKEN: appSessionToken,
  };

  // Launch Backend (strictly bound to 127.0.0.1)
  if (bundledBackend) {
    backendProc = spawn(bundledBackend, ["--port", String(backendPort)], {
      cwd: path.dirname(bundledBackend),
      env: envWithFfmpeg,
      windowsHide: true,
    });
  } else {
    backendProc = spawn(
      PYTHON_EXE,
      ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(backendPort)],
      { cwd: BACKEND_DIR, env: envWithFfmpeg, windowsHide: true }
    );
  }

  // Launch Frontend
  if (bundledFrontend) {
    staticServer = await serveStaticFolder(bundledFrontend, frontendPort);
  } else {
    const outDir = path.join(FRONTEND_DIR, "out");
    if (fs.existsSync(path.join(outDir, "index.html"))) {
      staticServer = await serveStaticFolder(outDir, frontendPort);
    } else {
      const nextCli = path.join(FRONTEND_DIR, "node_modules", "next", "dist", "bin", "next");
      frontendProc = spawn(process.execPath, [nextCli, "start", "-p", String(frontendPort)], {
        cwd: FRONTEND_DIR,
        env: { ...envWithFfmpeg, ELECTRON_RUN_AS_NODE: "1" },
        windowsHide: true,
      });
    }
  }

  await waitForServer(`http://127.0.0.1:${backendPort}/docs`);
  await waitForServer(`http://127.0.0.1:${frontendPort}`);
  syncSettingsToBackend();
  return { backendPort, frontendPort };
}

function startClipboardWatcher() {
  const supportedRegex =
    /^https?:\/\/(www\.)?(youtube\.com|youtu\.be|tiktok\.com|vt\.tiktok\.com|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|soundcloud\.com)\/.+/i;
  setInterval(() => {
    if (!settings || !settings.autoDetectClipboard || !mainWindow) return;
    const text = (clipboard.readText() || "").trim();
    if (text && text !== lastClipboardText && supportedRegex.test(text)) {
      lastClipboardText = text;
      mainWindow.webContents
        .executeJavaScript(
          `window.dispatchEvent(new CustomEvent('clipboard-url-detected', { detail: ${JSON.stringify(text)} }));`
        )
        .catch(() => {});
    }
  }, 1500);
}

function updateTrayMenu() {
  if (!tray || !settings) return;
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Universal Downloader", click: () => mainWindow && mainWindow.show() },
      {
        label: "Clipboard Auto-Detect",
        type: "checkbox",
        checked: Boolean(settings.autoDetectClipboard),
        click: (item) => {
          settings.autoDetectClipboard = item.checked;
          persistSettings();
          if (mainWindow) {
            mainWindow.webContents.send("settings:changed", settings);
          }
        },
      },
      { type: "separator" },
      {
        label: "Quit Completely",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ])
  );
}

function registerIpcHandlers() {
  ipcMain.handle("app:token", () => {
    return appSessionToken;
  });

  ipcMain.handle("settings:get", () => {
    return settings || loadSettings();
  });

  ipcMain.handle("settings:update", (_event, patch) => {
    if (!patch || typeof patch !== "object") return settings;
    if (typeof patch.autoDetectClipboard === "boolean") {
      settings.autoDetectClipboard = patch.autoDetectClipboard;
    }
    if (typeof patch.minimizeToTray === "boolean") {
      settings.minimizeToTray = patch.minimizeToTray;
    }
    if (typeof patch.notifyWhenFinished === "boolean") {
      settings.notifyWhenFinished = patch.notifyWhenFinished;
    }
    if ([1, 2, 3, 5].includes(Number(patch.maxConcurrent))) {
      settings.maxConcurrent = Number(patch.maxConcurrent);
    }
    if (patch.theme === "light" || patch.theme === "dark") {
      settings.theme = patch.theme;
    }
    persistSettings();
    syncSettingsToBackend();
    updateTrayMenu();
    return settings;
  });

  ipcMain.handle("dialog:pick-folder", async () => {
    if (!mainWindow) return settings;
    const res = await dialog.showOpenDialog(mainWindow, {
      title: "Select Save Folder",
      defaultPath: settings.saveFolder,
      properties: ["openDirectory", "createDirectory"],
    });
    if (!res.canceled && res.filePaths && res.filePaths[0]) {
      settings.saveFolder = path.resolve(res.filePaths[0]);
      persistSettings();
      syncSettingsToBackend();
    }
    return settings;
  });

  ipcMain.handle("shell:open-folder", async (_event, targetPath) => {
    const allowedRoot = settings.saveFolder;
    fs.mkdirSync(allowedRoot, { recursive: true });
    if (targetPath && typeof targetPath === "string" && isWithinAllowedFolder(targetPath, allowedRoot)) {
      const realTarget = fs.realpathSync(targetPath);
      if (fs.existsSync(realTarget) && fs.statSync(realTarget).isFile()) {
        shell.showItemInFolder(realTarget);
        return { opened: realTarget };
      }
      await shell.openPath(realTarget);
      return { opened: realTarget };
    }
    const realRoot = fs.realpathSync(allowedRoot);
    await shell.openPath(realRoot);
    return { opened: realRoot };
  });

  ipcMain.handle("notification:show", (_event, payload) => {
    if (!settings || !settings.notifyWhenFinished) return false;
    if (Notification.isSupported() && payload && payload.title) {
      new Notification({
        title: String(payload.title),
        body: payload.body ? String(payload.body) : "",
      }).show();
      return true;
    }
    return false;
  });
}

app.whenReady().then(async () => {
  if (process.platform === "win32") {
    app.setAppUserModelId("com.universaldownloader.app");
  }
  loadSettings();
  registerIpcHandlers();
  const { backendPort, frontendPort } = await startServices();

  mainWindow = new BrowserWindow({
    width: 1120,
    height: 800,
    minWidth: 820,
    minHeight: 620,
    title: "Universal Downloader",
    icon: APP_ICON_PATH,
    autoHideMenuBar: true,
    backgroundColor: "#0a0a0f",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(
    `http://localhost:${frontendPort}?api_port=${backendPort}&token=${appSessionToken}`
  );

  mainWindow.on("close", (e) => {
    if (!isQuitting && settings && settings.minimizeToTray) {
      e.preventDefault();
      mainWindow.hide();
    } else {
      isQuitting = true;
      cleanupChildProcesses();
      app.quit();
    }
  });

  const trayIcon =
    APP_ICON_PATH && fs.existsSync(APP_ICON_PATH)
      ? nativeImage.createFromPath(APP_ICON_PATH)
      : nativeImage.createFromDataURL(TRAY_ICON_DATA_URL);
  tray = new Tray(trayIcon);
  tray.setToolTip("Universal Downloader");
  updateTrayMenu();
  tray.on("click", () => mainWindow && mainWindow.show());

  startClipboardWatcher();
});

app.on("window-all-closed", () => {
  if (!settings || !settings.minimizeToTray) {
    isQuitting = true;
    cleanupChildProcesses();
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  cleanupChildProcesses();
});
