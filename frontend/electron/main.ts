import { app, BrowserWindow, shell, ipcMain } from "electron";
import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import * as path from "path";
import * as http from "http";
import * as net from "net";

const BACKEND_HOST = "127.0.0.1";
const isDev = !app.isPackaged;

let backendPort = 8000;
let backendUrl = `http://${BACKEND_HOST}:${backendPort}`;
let mainWindow: BrowserWindow | null = null;
let backendProcess: ChildProcessWithoutNullStreams | null = null;

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
