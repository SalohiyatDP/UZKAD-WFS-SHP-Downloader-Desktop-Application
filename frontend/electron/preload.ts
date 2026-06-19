import { contextBridge, ipcRenderer } from "electron";

// Minimal, safe bridge exposed to the renderer. The renderer talks to the
// backend over HTTP/WebSocket; here we only expose helpers that need the main
// process (resolving the backend URL, opening external links).
contextBridge.exposeInMainWorld("uzkad", {
  getBackendUrl: (): Promise<string> => ipcRenderer.invoke("get-backend-url"),
  openExternal: (url: string): Promise<void> =>
    ipcRenderer.invoke("open-external", url),
  openPath: (target: string): Promise<string> =>
    ipcRenderer.invoke("open-path", target),
  openLogin: (loginUrl: string): Promise<void> =>
    ipcRenderer.invoke("open-login", loginUrl),
  importSession: (): Promise<unknown> => ipcRenderer.invoke("import-session"),
  logoutSession: (): Promise<unknown> => ipcRenderer.invoke("logout-session"),
});
