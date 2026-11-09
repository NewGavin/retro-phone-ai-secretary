// 一次性脚本：把 dsh-idle-watchdog 写进桌面 profile 的 bundles，并生成 API secret。
// 说明：desktop profile 由桌面端应用独占管理，CLI `dsh plugin` 会拒绝；
// 这里按插件管理器的同一套落盘规则手工落盘，随后依赖 HMR 热装配。
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PROFILE = 'C:/Users/Gavin/.dsh/profiles/desktop/package.json';
const SECRET_DIR = 'C:/Users/Gavin/.dsh/idle-watchdog';
const SECRET_FILE = path.join(SECRET_DIR, 'api-secret');

const profile = JSON.parse(fs.readFileSync(PROFILE, 'utf8'));
const bundles = profile.dsh.profile.bundles;
if (!bundles.includes('dsh-idle-watchdog')) {
  bundles.push('dsh-idle-watchdog');
}
fs.writeFileSync(PROFILE, JSON.stringify(profile, null, 2) + '\n', 'utf8');
console.log('bundles =', bundles.join(', '));

fs.mkdirSync(SECRET_DIR, { recursive: true });
if (!fs.existsSync(SECRET_FILE)) {
  fs.writeFileSync(SECRET_FILE, crypto.randomBytes(32).toString('hex'), { mode: 0o600 });
}
console.log('secret-file =', SECRET_FILE);
console.log('secret =', fs.readFileSync(SECRET_FILE, 'utf8'));
