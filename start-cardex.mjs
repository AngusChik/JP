import { execSync, spawn } from "child_process";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(__dirname, "..", "cardex", "apps", "web");
const nextBin = resolve(
  __dirname,
  "..",
  "cardex",
  "node_modules",
  ".pnpm",
  "next@15.5.14_react-dom@19.2.4_react@19.2.4__react@19.2.4",
  "node_modules",
  "next",
  "dist",
  "bin",
  "next"
);

const port = process.env.PORT || "3000";

const child = spawn(process.execPath, [nextBin, "dev", "--turbopack", "--port", port], {
  cwd: webDir,
  stdio: "inherit",
  env: { ...process.env },
});

child.on("exit", (code) => process.exit(code ?? 0));
