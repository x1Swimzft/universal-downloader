#!/usr/bin/env node
// Read-only release guard: fails when release metadata and artifacts disagree.
// Usage: node scripts/verify-release.mjs [release-dir]   (default: <repo>/release)
import { createHash } from 'node:crypto';
import { createReadStream, existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const releaseDir = resolve(process.argv[2] ?? join(repo, 'release'));

const failures = [];
const pass = (m) => console.log(`ok   ${m}`);
const fail = (m) => {
  failures.push(m);
  console.log(`FAIL ${m}`);
};

if (!existsSync(releaseDir)) {
  console.error(`FAIL release directory not found: ${releaseDir}`);
  console.error('     Build it first or point the guard at a build output folder:');
  console.error('     node scripts/verify-release.mjs <release-dir>');
  process.exit(1);
}

// Released assets are GitHub-sanitized (spaces -> hyphens/dots); local builder output keeps
// spaces, so compare names with separators normalized.
// shortcut: only space/dot->hyphen normalization, extend if electron-builder renames artifacts.
const normalize = (name) => name.toLowerCase().replace(/[\s._]+/g, '-');

// Windows tooling writes some of these files as UTF-16LE with a BOM.
function readText(file) {
  const buf = readFileSync(file);
  if (buf[0] === 0xff && buf[1] === 0xfe) return { text: buf.toString('utf16le').replace(/^\uFEFF/, ''), encoding: 'UTF-16LE' };
  if (buf[0] === 0xfe && buf[1] === 0xff) return { text: buf.swap16().toString('utf16le').replace(/^\uFEFF/, ''), encoding: 'UTF-16BE' };
  return { text: buf.toString('utf8').replace(/^\uFEFF/, ''), encoding: 'UTF-8' };
}

const listing = readdirSync(releaseDir);
const actualName = (releasedName) => listing.find((f) => normalize(f) === normalize(releasedName));
const pathOf = (releasedName) => {
  const found = actualName(releasedName);
  return found ? join(releaseDir, found) : null;
};

async function hashFile(file) {
  return new Promise((res, rej) => {
    const sha512 = createHash('sha512');
    const sha256 = createHash('sha256');
    createReadStream(file)
      .on('data', (chunk) => {
        sha512.update(chunk);
        sha256.update(chunk);
      })
      .on('error', rej)
      .on('end', () => res({ sha512: sha512.digest('base64'), sha256: sha256.digest('hex').toUpperCase() }));
  });
}

// shortcut: flat electron-builder latest.yml shape only; swap in a YAML parser if nesting grows.
function parseLatestYml(text) {
  const doc = { files: [] };
  const unquote = (v) => v.replace(/^(['"])(.*)\1$/, '$2');
  let inFiles = false;
  let current = null;
  for (const raw of text.split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    const item = raw.match(/^\s*-\s*(\w+):\s*(.*)$/);
    if (item) {
      current = {};
      doc.files.push(current);
      current[item[1]] = unquote(item[2]);
      inFiles = true;
      continue;
    }
    const key = raw.match(/^(\w+):\s*(.*)$/);
    if (key) {
      const [, k, v] = key;
      inFiles = k === 'files' && v === '';
      current = null;
      if (!inFiles) doc[k] = v === '' ? [] : unquote(v);
      continue;
    }
    const nested = raw.match(/^\s+(\w+):\s*(.*)$/);
    if (nested && inFiles && current) current[nested[1]] = unquote(nested[2]);
  }
  return doc;
}

// --- latest.yml -----------------------------------------------------------
const ymlPath = join(releaseDir, 'latest.yml');
let yml = null;
if (!existsSync(ymlPath)) {
  fail('latest.yml is missing from the release directory');
} else {
  try {
    const doc = parseLatestYml(readText(ymlPath).text);
    if (!doc.version && !doc.files?.length) throw new Error('not a latest.yml (no version or files)');
    yml = doc;
    pass('latest.yml parses');
  } catch (err) {
    fail(`latest.yml does not parse: ${err.message}`);
  }
}

const version = yml?.version;
const entry = yml?.files?.[0];
if (yml && !version) fail('latest.yml has no version');
if (yml && !entry) fail('latest.yml has no files[0] entry');

// --- 1. installer naming --------------------------------------------------
const installerName = version ? `Universal-Downloader-Setup-${version}.exe` : null;
if (yml && installerName) {
  if (yml.path !== installerName) fail(`latest.yml path "${yml.path}" is not "${installerName}"`);
  else pass(`latest.yml path is ${installerName}`);
  if (entry?.url !== installerName) fail(`latest.yml files[0].url "${entry?.url}" is not "${installerName}"`);
  else pass('latest.yml files[0].url matches path');
}

// --- 2. installer integrity ----------------------------------------------
const installerPath = installerName ? pathOf(installerName) : null;
const hashes = new Map();
if (installerName && !installerPath) {
  fail(`installer ${installerName} not found in ${releaseDir}`);
} else if (installerPath) {
  const size = statSync(installerPath).size;
  const expectedSize = Number(entry?.size ?? yml?.size);
  if (!Number.isFinite(expectedSize)) fail('latest.yml has no usable installer size');
  else if (size !== expectedSize) fail(`installer size ${size} != latest.yml size ${expectedSize}`);
  else pass(`installer size ${size}`);

  const sums = await hashFile(installerPath);
  hashes.set(installerPath, sums);
  const expectedSha = entry?.sha512 ?? yml?.sha512;
  if (!expectedSha) fail('latest.yml has no installer sha512');
  else if (sums.sha512 !== expectedSha) fail(`installer sha512 mismatch: ${sums.sha512}`);
  else pass('installer sha512 matches latest.yml');
}

// --- 3. version consistency ----------------------------------------------
const readJsonVersion = (rel) => {
  const file = join(repo, rel);
  if (!existsSync(file)) return { skip: `${rel} not found` };
  try {
    const { version: v } = JSON.parse(readFileSync(file, 'utf8'));
    return v ? { version: v } : { skip: `${rel} has no version field` };
  } catch (err) {
    return { version: null, error: `${rel} is not valid JSON: ${err.message}` };
  }
};
const backendVersion = () => {
  const file = join(repo, 'backend', 'app', 'main.py');
  if (!existsSync(file)) return { skip: 'backend/app/main.py not found' };
  const src = readFileSync(file, 'utf8');
  const product = src.match(/\b(?:APP_VERSION|__version__)\s*=\s*['"]([^'"]+)['"]/);
  if (product) return { version: product[1] };
  const api = src.match(/FastAPI\([\s\S]*?\bversion\s*=\s*['"]([^'"]+)['"]/);
  // FastAPI's version is the API schema version, not the product release version.
  return { skip: api ? `backend exposes only FastAPI schema version ${api[1]}` : 'backend exposes no version' };
};

if (version) {
  const sources = [
    ['desktop/package.json', readJsonVersion('desktop/package.json')],
    ['frontend/package.json', readJsonVersion('frontend/package.json')],
    ['backend', backendVersion()],
  ];
  for (const [label, res] of sources) {
    if (res.error) fail(res.error);
    else if (res.skip) pass(`version check skipped: ${res.skip}`);
    else if (res.version !== version) fail(`${label} version ${res.version} != latest.yml ${version}`);
    else pass(`${label} version ${res.version}`);
  }
}

// --- 4. required artifacts -----------------------------------------------
const required = version
  ? [
      installerName,
      `${installerName}.blockmap`,
      `Universal-Downloader-${version}-win.zip`,
      'latest.yml',
      `SHA256SUMS-${version}.txt`,
    ]
  : ['latest.yml'];
const located = new Map();
for (const name of required) {
  const found = pathOf(name);
  if (found) {
    located.set(name, found);
    pass(`found ${actualName(name)}`);
  } else {
    fail(`missing required artifact ${name}`);
  }
}

// --- 5. SHA256SUMS -------------------------------------------------------
const role = (name) => {
  const base = name.trim().split(/[\\/]/).pop();
  if (base === 'latest.yml') return 'latest.yml';
  if (base.endsWith('.blockmap')) return 'blockmap';
  if (base.endsWith('.zip')) return 'zip';
  if (base.endsWith('.exe')) return 'installer';
  return null;
};

const sumsName = version ? `SHA256SUMS-${version}.txt` : null;
const sumsPath = sumsName ? pathOf(sumsName) : null;
if (sumsPath) {
  const byRole = new Map();
  for (const [name, file] of located) {
    const r = role(name);
    if (r && r !== 'latest.yml') byRole.set(r, file);
  }

  const sums = readText(sumsPath);
  pass(`${actualName(sumsName)} is ${sums.encoding}`);
  const lines = sums.text.split(/\r?\n/).filter((l) => l.trim());
  const seen = new Map();
  for (const line of lines) {
    const m = line.match(/^([a-fA-F0-9]{64})\s+\*?(.+)$/);
    if (!m) {
      fail(`SHA256SUMS line is not "<sha256>  <file>": ${line}`);
      continue;
    }
    const [, expected, listed] = m;
    const r = role(listed);
    if (!r) {
      fail(`SHA256SUMS entry maps to no known artifact: ${listed}`);
      continue;
    }
    if (seen.has(r)) {
      fail(`SHA256SUMS lists two ${r} entries: ${seen.get(r)} and ${listed}`);
      continue;
    }
    seen.set(r, listed);

    const target = r === 'latest.yml' ? join(releaseDir, 'latest.yml') : byRole.get(r);
    if (!target || !existsSync(target)) {
      fail(`SHA256SUMS lists ${listed} but no ${r} artifact was found`);
      continue;
    }
    if (!hashes.has(target)) hashes.set(target, await hashFile(target));
    const actual = hashes.get(target).sha256;
    if (actual !== expected.toUpperCase()) fail(`sha256 mismatch for ${listed} (listed as ${r}): ${actual}`);
    else pass(`sha256 ${actualName(listed) ?? listed}`);
  }
}

// --- 6. release notes hash table -----------------------------------------
// The published notes must describe the files being shipped, not an earlier build.
const notesPath = version ? join(repo, 'docs', 'releases', `v${version}.md`) : null;
if (notesPath && !existsSync(notesPath)) {
  fail(`release notes missing: docs/releases/v${version}.md`);
} else if (notesPath) {
  const listed = new Map();
  for (const line of readText(notesPath).text.split(/\r?\n/)) {
    const m = line.match(/^([a-fA-F0-9]{64})\s{2,}(\S.*?)\s*$/);
    if (m) listed.set(m[2].trim(), m[1].toUpperCase());
  }
  if (!listed.size) {
    fail(`release notes have no SHA-256 table: docs/releases/v${version}.md`);
  }
  const rolesSeen = new Set();
  for (const [name, expected] of listed) {
    const file = pathOf(name);
    if (!file) {
      fail(`release notes list ${name} but it is not in ${releaseDir}`);
      continue;
    }
    const r = role(name);
    if (r) rolesSeen.add(r);
    if (!hashes.has(file)) hashes.set(file, await hashFile(file));
    const actual = hashes.get(file).sha256;
    if (actual !== expected) fail(`release notes sha256 mismatch for ${name}: ${actual}`);
    else pass(`notes sha256 ${name}`);
  }
  for (const r of ['installer', 'blockmap', 'zip', 'latest.yml']) {
    if (!rolesSeen.has(r)) fail(`release notes do not list a ${r} hash`);
  }
}

// --- 7. backend engine freshness -----------------------------------------
// desktop/backend-engine is a prebuilt PyInstaller folder; nothing else checks it,
// and a stale copy ships an old API without failing any other test.
const engineExe = join(repo, 'desktop', 'backend-engine', 'backend-engine.exe');
const backendApp = join(repo, 'backend', 'app');
if (!existsSync(engineExe)) {
  fail(`backend-engine.exe not found at ${engineExe}`);
} else if (!existsSync(backendApp)) {
  fail(`backend/app not found at ${backendApp}`);
} else {
  const newestSource = (dir) => {
    let newest = 0;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === '__pycache__') continue;
        newest = Math.max(newest, newestSource(full));
      } else if (entry.name.endsWith('.py')) {
        newest = Math.max(newest, statSync(full).mtimeMs);
      }
    }
    return newest;
  };
  const sourceTime = newestSource(backendApp);
  const engineTime = statSync(engineExe).mtimeMs;
  if (sourceTime > engineTime) {
    fail(
      `backend-engine.exe is older than backend/app sources - rebuild it ` +
        `(pyinstaller backend-engine.spec) and copy backend/dist/backend-engine into desktop/`
    );
  } else {
    pass('backend-engine.exe is newer than backend/app sources');
  }
}

// --- result --------------------------------------------------------------
console.log('');
if (failures.length) {
  console.log(`${failures.length} release check(s) failed in ${releaseDir}`);
  process.exit(1);
}
console.log(`all release checks passed in ${releaseDir}`);
process.exit(0);
