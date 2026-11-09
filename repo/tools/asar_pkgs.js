// 扫描 app.asar 里 @deepseek-ai/* 的 package.json，找带 bin 的包（可能的 CLI）
const fs = require('fs');
const asar = process.argv[2] || 'D:/DSH/resources/app.asar';
const filter = (process.argv[3] || '').toLowerCase();

const fd = fs.openSync(asar, 'r');
const b = Buffer.alloc(8);
fs.readSync(fd, b, 0, 8, 0);
const headerSize = b.readUInt32LE(4);
const hb = Buffer.alloc(headerSize);
fs.readSync(fd, hb, 0, headerSize, 8);
const text = hb.toString('utf8');
const start = text.indexOf('{"files"');
let depth = 0, inStr = false, esc = false, end = -1;
for (let i = start; i < text.length; i++) {
  const c = text[i];
  if (inStr) {
    if (esc) esc = false;
    else if (c === '\\') esc = true;
    else if (c === '"') inStr = false;
  } else if (c === '"') inStr = true;
  else if (c === '{') depth++;
  else if (c === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}
const header = JSON.parse(text.slice(start, end));
const dataStart = 8 + headerSize;

function readFileNode(node) {
  const out = Buffer.alloc(node.size);
  fs.readSync(fd, out, 0, node.size, dataStart + Number(node.offset));
  return out.toString('utf8');
}

const results = [];
(function walk(node, prefix) {
  for (const [name, ent] of Object.entries(node.files || {})) {
    const p = prefix ? prefix + '/' + name : name;
    if (ent.files) { walk(ent, p); continue; }
    if (!/dsh\/node_modules\/@deepseek-ai\/[^/]+\/package\.json$/.test(p)) continue;
    try {
      const j = JSON.parse(readFileNode(ent));
      if (filter && !((j.name || '') + ' ' + (j.description || '')).toLowerCase().includes(filter)) continue;
      results.push({ p, name: j.name, version: j.version, bin: j.bin, main: j.main, desc: (j.description || '').slice(0, 90) });
    } catch (e) { /* 忽略解析失败 */ }
  }
})(header, '');

results.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
for (const r of results) {
  const bin = r.bin ? JSON.stringify(r.bin) : '';
  console.log(`${r.name}@${r.version}${bin ? '  BIN=' + bin : ''}${r.main ? '  main=' + r.main : ''}\n    ${r.desc}`);
}
console.log('\n共', results.length, '个 @deepseek-ai 包');
