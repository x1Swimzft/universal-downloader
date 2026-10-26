const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  getAppToken: () => ipcRenderer.invoke("app:token"),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  updateSettings: (patch) => ipcRenderer.invoke("settings:update", patch),
  pickFolder: () => ipcRenderer.invoke("dialog:pick-folder"),
  pickCookiesFile: () => ipcRenderer.invoke("dialog:pick-cookies"),
  openFolder: (targetPath) => ipcRenderer.invoke("shell:open-folder", targetPath),
  notify: (title, body) => ipcRenderer.invoke("notification:show", { title, body }),
  startDrag: (filePath) => ipcRenderer.invoke("file:start-drag", filePath),
  onSettingsUpdated: (callback) => {
    const handler = (_event, updated) => callback(updated);
    ipcRenderer.on("settings:changed", handler);
    return () => ipcRenderer.removeListener("settings:changed", handler);
  },
});
