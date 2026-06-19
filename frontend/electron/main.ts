import { app, BrowserWindow, shell, ipcMain, session } from "electron";
import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import * as path from "path";
import * as http from "http";
import * as net from "net";

const BACKEND_HOST = "127.0.0.1";
const isDev = !app.isPackaged;
const PORTAL_PARTITION = "persist:uzkad-portal";
const DEFAULT_LOGIN_URL = "https://mulk.kadastr.uz/index.jsp";

let backendPort = 8000;
let backendUrl = `http://${BACKEND_HOST}:${backendPort}`;
let mainWindow: BrowserWindow | null = null;
let loginWindow: BrowserWindow | null = null;
let backendProcess: ChildProcessWithoutNullStreams | null = null;
let capturedAuth: string | null = null;
let captureInstalled = false;

/** Find a free TCP port so the app works even if 8000 is taken. */
function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, BACKEND_HOST, () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 8000;
      srv.close(() => resolve(port));
    });
  });
}

/** Resolve the backend directory in both dev and packaged builds. */
function backendDir(): string {
  if (isDev) {
    return path.resolve(__dirname, "..", "..", "backend");
  }
  // electron-builder copies backend into resources/backend.
  return path.join(process.resourcesPath, "backend");
}

/** Pick a python executable. Allow override via UZKAD_PYTHON. */
function pythonExecutable(): string {
  if (process.env.UZKAD_PYTHON) return process.env.UZKAD_PYTHON;
  return process.platform === "win32" ? "python" : "python3";
}

function startBackend(): void {
  const cwd = backendDir();
  const py = pythonExecutable();
  console.log(`[backend] starting: ${py} -m app.main --port ${backendPort} (cwd=${cwd})`);

  backendProcess = spawn(
    py,
    ["-m", "app.main", "--host", BACKEND_HOST, "--port", String(backendPort)],
    { cwd, env: { ...process.env, PYTHONUNBUFFERED: "1" } }
  );

  backendProcess.stdout.on("data", (d) => console.log(`[backend] ${d}`));
  backendProcess.stderr.on("data", (d) => console.error(`[backend] ${d}`));
  backendProcess.on("exit", (code) =>
    console.log(`[backend] exited with code ${code}`)
  );
}

/** Poll the health endpoint until the backend is ready (or times out). */
function waitForBackend(retries = 60): Promise<boolean> {
  return new Promise((resolve) => {
    const attempt = (n: number) => {
      const req = http.get(`${backendUrl}/api/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve(true);
        retry(n);
      });
      req.on("error", () => retry(n));
      req.setTimeout(1000, () => {
        req.destroy();
        retry(n);
      });
    };
    const retry = (n: number) => {
      if (n <= 0) return resolve(false);
      setTimeout(() => attempt(n - 1), 500);
    };
    attempt(retries);
  });
}

/** Minimal JSON POST helper to the local backend. */
function postJson(url: string, body: unknown): Promise<any> {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const u = new URL(url);
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": data.length,
        },
      },
      (res) => {
        let chunks = "";
        res.on("data", (d) => (chunks += d));
        res.on("end", () => {
          try {
            resolve(JSON.parse(chunks || "{}"));
          } catch {
            resolve({});
          }
        });
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

function portalSession(): Electron.Session {
  return session.fromPartition(PORTAL_PARTITION);
}

/** Capture the Authorization bearer token used by kadastr.uz API/WFS calls. */
function installPortalCapture(): void {
  if (captureInstalled) return;
  const ses = portalSession();
  ses.webRequest.onBeforeSendHeaders((details, cb) => {
    try {
      const url = details.url || "";
      if (url.includes("kadastr.uz")) {
        const h = details.requestHeaders || {};
        const auth = (h["Authorization"] || h["authorization"]) as string | undefined;
        if (auth && /bearer\s+/i.test(auth)) capturedAuth = auth;
      }
    } catch {
      /* ignore */
    }
    cb({ requestHeaders: details.requestHeaders });
  });
  captureInstalled = true;
}

/** Open the cadastre portal window (mulk.kadastr.uz, or a supplied link). */
async function openLoginWindow(loginUrl: string): Promise<void> {
  installPortalCapture();
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.focus();
    return;
  }
  loginWindow = new BrowserWindow({
    width: 1200,
    height: 860,
    title: "UZKAD — Portal (mulk.kadastr.uz)",
    backgroundColor: "#ffffff",
    parent: mainWindow ?? undefined,
    webPreferences: {
      partition: PORTAL_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // Allow OneID / ERI popups to open within the same (persistent) session.
  loginWindow.webContents.setWindowOpenHandler(() => ({ action: "allow" }));
  loginWindow.on("closed", () => {
    loginWindow = null;
  });
  await loginWindow.loadURL(loginUrl || DEFAULT_LOGIN_URL);
}

/** Collect kadastr.uz cookies + captured token and send them to the backend. */
async function importSession(): Promise<any> {
  const ses = portalSession();
  const all = await ses.cookies.get({});
  const cookies: Record<string, string> = {};
  for (const c of all) {
    if ((c.domain || "").includes("kadastr.uz")) cookies[c.name] = c.value;
  }
  const headers: Record<string, string> = {};
  if (capturedAuth) headers["Authorization"] = capturedAuth;
  return postJson(`${backendUrl}/api/session/cookies`, {
    cookies,
    headers,
    source: "in-app",
  });
}

/** Clear the captured portal session everywhere. */
async function logoutSession(): Promise<any> {
  capturedAuth = null;
  try {
    await portalSession().clearStorageData();
  } catch {
    /* ignore */
  }
  if (loginWindow && !loginWindow.isDestroyed()) loginWindow.close();
  return postJson(`${backendUrl}/api/session/clear`, {});
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 800,
    minWidth: 900,
    minHeight: 640,
    title: "UZKAD SHP Downloader",
    backgroundColor: "#0f172a",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Open external links in the system browser (so users can log in to UZKAD).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    await mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    await mainWindow.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("get-backend-url", () => backendUrl);
ipcMain.handle("open-external", (_evt, url: string) => shell.openExternal(url));
ipcMain.handle("open-path", (_evt, target: string) => shell.openPath(target));
ipcMain.handle("open-login", (_evt, loginUrl: string) =>
  openLoginWindow(loginUrl || DEFAULT_LOGIN_URL)
);
ipcMain.handle("import-session", () => importSession());
ipcMain.handle("logout-session", () => logoutSession());

app.whenReady().then(async () => {
  try {
    backendPort = await findFreePort();
  } catch {
    backendPort = 8000;
  }
  backendUrl = `http://${BACKEND_HOST}:${backendPort}`;
  startBackend();
  const ready = await waitForBackend();
  if (!ready) {
    console.error("[backend] did not become ready in time");
  }
  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("quit", () => {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
});
