// Serves a directory as an electron-updater generic feed over http://127.0.0.1.
// Usage: node scripts/serve-update-feed.mjs [dir=release] [port=8099]
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import path from "node:path";

const dir = path.resolve(process.argv[2] ?? "release");
const port = Number(process.argv[3] ?? 8099);
const TYPES = {
  ".yml": "text/yaml",
  ".exe": "application/octet-stream",
  ".blockmap": "application/octet-stream",
  ".zip": "application/zip",
};

createServer((req, res) => {
  console.log(`${req.method} ${req.url}`);
  const rel = decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/^\/+/, "");
  const file = path.join(dir, rel);
  const inside = path.relative(dir, file);
  if (inside.startsWith("..") || path.isAbsolute(inside)) {
    res.writeHead(403).end("forbidden");
    return;
  }
  const stat = statSync(file, { throwIfNoEntry: false });
  if (!stat?.isFile()) {
    res.writeHead(404).end("not found");
    return;
  }

  const headers = {
    "content-type": TYPES[path.extname(file).toLowerCase()] ?? "application/octet-stream",
    "accept-ranges": "bytes",
  };
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? "");
  if (!range) {
    res.writeHead(200, { ...headers, "content-length": stat.size });
    if (req.method === "HEAD") return res.end();
    createReadStream(file).pipe(res);
    return;
  }

  const start = range[1] ? Number(range[1]) : 0;
  const end = range[2] ? Math.min(Number(range[2]), stat.size - 1) : stat.size - 1;
  if (start >= stat.size || start > end) {
    res.writeHead(416, { "content-range": `bytes */${stat.size}` }).end();
    return;
  }
  res.writeHead(206, {
    ...headers,
    "content-length": end - start + 1,
    "content-range": `bytes ${start}-${end}/${stat.size}`,
  });
  createReadStream(file, { start, end }).pipe(res);
}).listen(port, "127.0.0.1", () => {
  console.log(`serving ${dir} at http://127.0.0.1:${port}/`);
});
