// 读取 app.asar 头部并导出指定文件（修正版：按 JSON 大括号配对截取头部）
const fs = require('fs');
const asar = process.argv[2];
const want = process.argv[3] || 'package.json';

const fd = fs.openSync(asar, 'r');
const b = Buffer.alloc(8);
fs.readSync(fd, b, 0, 8, 0);
const headerSize = b.readUInt32LE(4);
const hb = Buffer.alloc(headerSize);
fs.readSync(fd, hb, 0, headerSize, 8);
const text = hb.toString('utf8');
const start = text.indexOf('{"files"');
if (start < 0) {
  console.log('未找到头部 JSON');
  process.exit(1);
}
let depth = 0, inStr = false, esc = false, end = -1;
for (let i = start; i < text.length; i++) {
  const c = text[i];
  if (inStr) {
    if (esc) esc = false;
    else if (c === '\\') esc = true;
    else if (c === '"') inStr = false;
  } else if (c === '"') inStr = true;
  else if (c === '{') depth++;
  else if (c === '}') {
    depth--;
    if (depth === 0) { end = i + 1; break; }
  }
}
const header = JSON.parse(text.slice(start, end));

function topKeys(node, prefix, out) {
  for (const [name, ent] of Object.entries(node.files || {})) {
    const p = prefix ? prefix + '/' + name : name;
    out.push({ path: p, dir: !!ent.files, size: ent.size });
  }
}

const base = text.slice(0, start);
// 数据区起始 = 8 + headerSize（asar 约定）
const dataStart = 8 + headerSize;

function findNode(parts) {
  let node = header;
  for (const p of parts) {
    if (!node.files || !node.files[p]) return null;
    node = node.files[p];
  }
  return node;
}

if (want === '--list') {
  const out = [];
  topKeys(header, '', out);
  for (const e of out) console.log((e.dir ? 'd ' : 'f ') + e.path + (e.size != null ? ' ' + e.size : ''));
  // 列出所有含 cli / bin 的顶层目录
  console.log('\n--- 名字含 cli/bin/headless 的条目 ---');
  const hits = [];
  (function walk(node, prefix) {
    for (const [name, ent] of Object.entries(node.files || {})) {
      const p = prefix ? prefix + '/' + name : name;
      if (/cli|headless|bin\b/i.test(name) && hits.length < 60) hits.push(p + (ent.files ? '/' : ' ' + ent.size));
      if (ent.files) walk(ent, p);
    }
  })(header, '');
  console.log(hits.join('\n'));
  process.exit(0);
}

const node = findNode(want.split('/'));
if (!node || node.files) {
  console.log('不是文件或不存在:', want);
  process.exit(1);
}
const out = Buffer.alloc(node.size);
fs.readSync(fd, out, 0, node.size, dataStart + Number(node.offset));
process.stdout.write(out.toString('utf8'));
