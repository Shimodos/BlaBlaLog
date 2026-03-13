const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  sendToBackend: (method, params) =>
    ipcRenderer.invoke("backend:send", { method, params }),
  getBackendStatus: () => ipcRenderer.invoke("backend:status"),
  onBackendEvent: (callback) =>
    ipcRenderer.on("backend:event", (_event, data) => callback(data)),
  onBackendLog: (callback) =>
    ipcRenderer.on("backend:log", (_event, line) => callback(line)),
  onBackendInitStatus: (callback) =>
    ipcRenderer.on("backend:init-status", (_event, status) => callback(status)),
  minimize: () => ipcRenderer.send("window:minimize"),
  maximize: () => ipcRenderer.send("window:maximize"),
  close: () => ipcRenderer.send("window:close"),
  showSaveDialog: (options) => ipcRenderer.invoke("dialog:save", options),
});
