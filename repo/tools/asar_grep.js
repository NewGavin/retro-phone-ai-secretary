// 在 app.asar 内按关键字搜索源码：node tools/asar_grep.js <asar> <needle> [路径正则] [最大命中数]
const fs = require('fs');
const asar = process.argv[2];
const needle = process.argv[3];
const pathRe = process.argv[4] ? new RegExp(process.argv[4], 'i') : /./;
const maxHits = Number(process.argv[5] || 20);

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

const hits = [];
function walk(node, prefix) {
  if (hits.length >= maxHits) return;
  for (const [name, ent] of Object.entries(node.files || {})) {
    if (hits.length >= maxHits) return;
    const p = prefix ? prefix + '/' + name : name;
    if (ent.files) { walk(ent, p); continue; }
    if (!ent.size || ent.size > 8 * 1024 * 1024) continue;
    if (!/\.(js|mjs|cjs|ts|tsx|json|md)$/i.test(name)) continue;
    if (!pathRe.test(p)) continue;
    const buf = Buffer.alloc(ent.size);
    try {
      fs.readSync(fd, buf, 0, ent.size, dataStart + Number(ent.offset));
    } catch { continue; }
    const s = buf.toString('utf8');
    const idx = s.indexOf(needle);
    if (idx >= 0) {
      const from = Math.max(0, idx - 200);
      hits.push({ p, size: ent.size, snippet: s.slice(from, idx + 400).replace(/\n/g, ' ⏎ ') });
      console.log('== ' + p + ' (' + ent.size + 'B)');
      console.log('   ' + s.slice(from, idx + 300).replace(/\n/g, ' ⏎ '));
    }
  }
}
walk(header, '');
console.log('\n检查完毕，命中 ' + hits.length + ' 个文件');
