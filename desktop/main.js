const { app, BrowserWindow, Tray, Menu, clipboard, nativeImage } = require("electron");
const { spawn, execSync } = require("child_process");
const path = require("path");
const net = require("net");
const http = require("http");
const fs = require("fs");

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
const FFMPEG_BIN = bundledBin || "C:\\Users\\Dataria\\Downloads\\ffmpeg-2026-10-01-git-0b01ed76aa-essentials_build\\bin";

// 2. Resolve Backend Executable
const bundledBackend = resolveAssetPath(path.join("backend-engine", "backend-engine.exe"));
const PYTHON_EXE = bundledBackend || path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe");

// 3. Resolve Static Frontend
const bundledFrontend = resolveAssetPath("frontend-out");

// ไอคอน 16x16 สีฟ้าคราม (Base64 PNG) ป้องกัน Tray ล่องหนบน Windows 11
const TRAY_ICON_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAySURBVDhPY/hPBAwUACYoTTYYNWDUgFEDRg0YNWDUgFEDRg1gIAtA00A1A0g1gIEBAJ8fH/H1461bAAAAAElFTkSuQmCC";

let mainWindow = null;
let tray = null;
let backendProc = null;
let frontendProc = null;
let staticServer = null;
let isQuitting = false;
let clipboardWatchEnabled = true;
let lastClipboardText = "";

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
      http.get(url, (res) => {
        if (res.statusCode < 500) return resolve(true);
        retry();
      }).on("error", retry);
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

  const envWithFfmpeg = {
    ...process.env,
    PATH: `${FFMPEG_BIN};${process.env.PATH || ""}`,
    NEXT_PUBLIC_API_URL: `http://127.0.0.1:${backendPort}/api`,
    PORT: String(frontendPort),
  };

  // Launch Backend
  if (bundledBackend) {
    backendProc = spawn(
      bundledBackend,
      ["--port", String(backendPort)],
      { cwd: path.dirname(bundledBackend), env: envWithFfmpeg, windowsHide: true }
    );
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
    const nextCli = path.join(FRONTEND_DIR, "node_modules", "next", "dist", "bin", "next");
    frontendProc = spawn(
      process.execPath,
      [nextCli, "start", "-p", String(frontendPort)],
      { cwd: FRONTEND_DIR, env: { ...envWithFfmpeg, ELECTRON_RUN_AS_NODE: "1" }, windowsHide: true }
    );
  }

  await waitForServer(`http://127.0.0.1:${backendPort}/docs`);
  await waitForServer(`http://127.0.0.1:${frontendPort}`);
  return { backendPort, frontendPort };
}

function startClipboardWatcher() {
  const supportedRegex = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be|tiktok\.com|vt\.tiktok\.com|instagram\.com|facebook\.com|fb\.watch|twitter\.com|x\.com|soundcloud\.com)\/.+/i;
  setInterval(() => {
    if (!clipboardWatchEnabled || !mainWindow) return;
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

app.whenReady().then(async () => {
  const { backendPort, frontendPort } = await startServices();

  mainWindow = new BrowserWindow({
    width: 1120,
    height: 800,
    minWidth: 820,
    minHeight: 620,
    title: "Universal Downloader",
    autoHideMenuBar: true,
    backgroundColor: "#09090b",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(`http://localhost:${frontendPort}?api_port=${backendPort}`);

  mainWindow.on("close", (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  const icon = nativeImage.createFromDataURL(TRAY_ICON_DATA_URL);
  tray = new Tray(icon);
  tray.setToolTip("Universal Downloader");

  const updateTrayMenu = () => {
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: "Open Universal Downloader", click: () => mainWindow.show() },
        {
          label: "Clipboard Auto-Detect",
          type: "checkbox",
          checked: clipboardWatchEnabled,
          click: (item) => {
            clipboardWatchEnabled = item.checked;
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
  };
  updateTrayMenu();
  tray.on("click", () => mainWindow.show());

  startClipboardWatcher();
});

app.on("before-quit", () => {
  isQuitting = true;
  killProcessTree(backendProc);
  killProcessTree(frontendProc);
  if (staticServer) {
    try { staticServer.close(); } catch (_) {}
  }
});
