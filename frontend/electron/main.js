// Clear ELECTRON_RUN_AS_NODE so Electron loads as GUI, not as plain Node
// (electron-builder & some IDEs set this variable)
if (process.env.ELECTRON_RUN_AS_NODE) {
  delete process.env.ELECTRON_RUN_AS_NODE;
}

const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn, execSync } = require("child_process");

let mainWindow = null;
let pythonProcess = null;

// Pending JSON-RPC requests awaiting responses from Python
const pendingRequests = new Map();
let requestId = 0;
let stdoutBuffer = "";

// On macOS/Linux, ensure venv python binaries have execute permission
// (electron-builder can strip +x when copying extraResources)
function ensureVenvExecutable(venvDir) {
  if (process.platform === "win32") return;
  const binDir = path.join(venvDir, "bin");
  if (!fs.existsSync(binDir)) return;
  try {
    execSync(`chmod +x "${binDir}"/python* 2>/dev/null || true`, { stdio: "ignore" });
  } catch { /* ignore */ }
}

// Auto-detect site-packages path inside a venv (handles different Python versions)
function findSitePackages(venvDir) {
  const isWin = process.platform === "win32";
  if (isWin) {
    return path.join(venvDir, "Scripts", "Lib", "site-packages");
  }
  // macOS/Linux: .venv/lib/python3.XX/site-packages — find the actual version
  const libDir = path.join(venvDir, "lib");
  if (fs.existsSync(libDir)) {
    try {
      const entries = fs.readdirSync(libDir).filter((e) => e.startsWith("python"));
      if (entries.length > 0) {
        return path.join(libDir, entries[0], "site-packages");
      }
    } catch { /* ignore */ }
  }
  // Fallback to python3.11
  return path.join(libDir, "python3.11", "site-packages");
}

function getPythonPath() {
  const isWin = process.platform === "win32";
  const ext = isWin ? ".exe" : "";
  const candidates = [];

  if (app.isPackaged) {
    // PyInstaller frozen backend inside resources/backend/
    const resBackend = path.join(process.resourcesPath, "backend");
    candidates.push({
      exe: path.join(resBackend, `voicescribe-backend${ext}`),
      args: ["serve"],
      cwd: resBackend,
    });
    // Fallback: venv inside resources/backend/
    const venvDir = path.join(resBackend, ".venv");
    ensureVenvExecutable(venvDir);
    // Try multiple python binary names (macOS venv may have python3 but not python)
    const pythonNames = isWin ? ["python.exe"] : ["python", "python3", "python3.11"];
    const binDir = isWin ? path.join(venvDir, "Scripts") : path.join(venvDir, "bin");
    for (const name of pythonNames) {
      candidates.push({
        exe: path.join(binDir, name),
        args: ["-m", "src.main", "serve"],
        cwd: resBackend,
      });
    }
  }

  // Dev / portable: backend is sibling folder
  const devBackend = path.resolve(__dirname, "..", "..", "backend");
  const devVenv = path.join(devBackend, ".venv");
  const devPythonNames = isWin ? ["python.exe"] : ["python", "python3", "python3.11"];
  const devBinDir = isWin ? path.join(devVenv, "Scripts") : path.join(devVenv, "bin");
  for (const name of devPythonNames) {
    candidates.push({
      exe: path.join(devBinDir, name),
      args: ["-m", "src.main", "serve"],
      cwd: devBackend,
    });
  }

  for (const c of candidates) {
    if (fs.existsSync(c.exe)) {
      return c;
    }
  }

  // Last resort: system python
  const fallbackCwd = app.isPackaged
    ? path.join(process.resourcesPath, "backend")
    : devBackend;
  if (isWin) {
    return { exe: "py", args: ["-3.11", "-m", "src.main", "serve"], cwd: fallbackCwd };
  }
  return { exe: "python3", args: ["-m", "src.main", "serve"], cwd: fallbackCwd };
}

function startPythonBackend() {
  // Write boot log to file for debugging
  const logFile = path.join(app.getPath("userData"), "boot.log");
  const log = (msg) => {
    const line = `${new Date().toISOString()} ${msg}`;
    console.log(line);
    try { fs.appendFileSync(logFile, line + "\n"); } catch (e) { /* ignore */ }
  };

  log(`[BOOT] isPackaged=${app.isPackaged}`);
  log(`[BOOT] __dirname=${__dirname}`);
  log(`[BOOT] resourcesPath=${process.resourcesPath}`);
  log(`[BOOT] userData=${app.getPath("userData")}`);

  const result = getPythonPath();
  const { exe, args, cwd } = result;
  log(`[BOOT] Starting Python: ${exe} ${args.join(" ")} in ${cwd}`);
  log(`[BOOT] exe exists: ${fs.existsSync(exe)}`);

  // Notify renderer about init progress
  function sendInitStatus(stage, message) {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend:init-status", { stage, message });
    }
  }

  try {
    sendInitStatus("starting", "Starting backend process...");

    // Set PYTHONPATH so embedded Python finds 'src' module + installed packages
    const isWin = process.platform === "win32";
    const sep = isWin ? ";" : ":";
    const venvDir = path.join(cwd, ".venv");
    const sitePackages = findSitePackages(venvDir);
    const pythonPath = [cwd, sitePackages].join(sep);
    const env = { ...process.env, PYTHONPATH: pythonPath };
    log(`[BOOT] PYTHONPATH=${pythonPath}`);
    pythonProcess = spawn(exe, args, { cwd, stdio: ["pipe", "pipe", "pipe"], env });

    sendInitStatus("loading", "Loading Python environment...");

    pythonProcess.stdout.setEncoding("utf8");
    pythonProcess.stdout.on("data", (data) => {
      stdoutBuffer += data;
      const lines = stdoutBuffer.split("\n");
      stdoutBuffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const response = JSON.parse(trimmed);

          // Response to a pending request (has numeric id)
          if (response.id !== undefined && response.id !== null && pendingRequests.has(response.id)) {
            const { resolve } = pendingRequests.get(response.id);
            pendingRequests.delete(response.id);
            resolve(response);
          }

          // Notification from backend (has method, no id) — forward to renderer
          if (response.method && !("id" in response) && mainWindow && !mainWindow.isDestroyed()) {
            // Only log non-spammy notifications (skip audio.levels which fires 10x/sec)
            if (response.method !== "audio.levels") {
              console.log("[notify]", response.method, JSON.stringify(response.params || {}).substring(0, 200));
            }
            mainWindow.webContents.send("backend:event", response);
          }
        } catch (e) {
          // Non-JSON line from Python (model download progress, etc.) — ignore
          console.log("[Python stdout]", trimmed.substring(0, 200));
        }
      }
    });

    pythonProcess.stderr.on("data", (data) => {
      const text = data.toString().trim();
      console.error("[Python]:", text);
      // Forward log lines to renderer for in-app Log page
      if (mainWindow && !mainWindow.isDestroyed()) {
        for (const line of text.split("\n")) {
          if (line.trim()) {
            mainWindow.webContents.send("backend:log", line.trim());
            // Detect init phases from stderr and forward as init-status
            const lower = line.toLowerCase();
            if (lower.includes("loading model") || lower.includes("downloading")) {
              sendInitStatus("models", line.trim());
            } else if (lower.includes("server") && lower.includes("start")) {
              sendInitStatus("ready", line.trim());
            } else if (lower.includes("import") || lower.includes("initializ")) {
              sendInitStatus("loading", line.trim());
            }
          }
        }
      }
    });

    pythonProcess.on("close", (code) => {
      console.log(`Python exited with code ${code}`);
      pythonProcess = null;
      for (const [id, { reject }] of pendingRequests) {
        reject(new Error("Python process terminated"));
        pendingRequests.delete(id);
      }
    });

    pythonProcess.on("error", (err) => {
      console.error("Failed to start Python:", err.message);
      pythonProcess = null;
    });
  } catch (err) {
    console.error("Error spawning Python:", err.message);
  }
}

function sendToPython(method, params) {
  return new Promise((resolve, reject) => {
    if (!pythonProcess || pythonProcess.killed) {
      reject(new Error("Python backend is not running"));
      return;
    }
    const id = ++requestId;
    const request = { jsonrpc: "2.0", id, method, params: params || {} };
    pendingRequests.set(id, { resolve, reject });

    // Timeout: 120s for heavy operations, 30s for others
    const timeout = (method === "stop_recording" || method === "start_recording") ? 120000 : 30000;
    setTimeout(() => {
      if (pendingRequests.has(id)) {
        pendingRequests.delete(id);
        reject(new Error(`Request timed out after ${timeout / 1000}s`));
      }
    }, timeout);

    try {
      pythonProcess.stdin.write(JSON.stringify(request) + "\n");
    } catch (err) {
      pendingRequests.delete(id);
      reject(err);
    }
  });
}

function killPythonProcess() {
  if (pythonProcess && !pythonProcess.killed) {
    pythonProcess.kill();
    pythonProcess = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: "VoiceScribe",
    frame: false,
    titleBarStyle: "hidden",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const distPath = path.join(__dirname, "..", "dist", "index.html");

  if (app.isPackaged || fs.existsSync(distPath)) {
    mainWindow.loadFile(distPath);
  } else {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// App lifecycle
app.whenReady().then(() => {
  // IPC Handlers — must be registered after app is ready
  ipcMain.handle("backend:send", async (_event, { method, params }) => {
    try {
      return await sendToPython(method, params);
    } catch (err) {
      return { error: { code: -1, message: err.message } };
    }
  });

  ipcMain.handle("backend:status", () => ({
    running: pythonProcess !== null && !pythonProcess.killed,
  }));

  ipcMain.on("window:minimize", () => {
    if (mainWindow) mainWindow.minimize();
  });

  ipcMain.on("window:maximize", () => {
    if (mainWindow) {
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
      } else {
        mainWindow.maximize();
      }
    }
  });

  ipcMain.on("window:close", () => {
    if (mainWindow) mainWindow.close();
  });

  // Save file dialog
  ipcMain.handle("dialog:save", async (_event, { defaultName, filters }) => {
    if (!mainWindow) return null;
    const result = await dialog.showSaveDialog(mainWindow, {
      defaultPath: defaultName || "transcript",
      filters: filters || [{ name: "All Files", extensions: ["*"] }],
    });
    if (result.canceled) return null;
    return result.filePath;
  });

  createWindow();
  startPythonBackend();
});

app.on("before-quit", () => {
  killPythonProcess();
});

app.on("window-all-closed", () => {
  killPythonProcess();
  app.quit();
});
