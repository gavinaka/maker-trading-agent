// 清理过期动态采集图：读完/推完 Notion 后无保留价值。
//   - data_sources/inbox/<YYYY-MM-DD>/   每日 7 张源截图
//   - outputs/blockbeats/<YYYY-MM-DD>_*.png  每日基本面快讯卡
// 只保留最近 CLEANUP_KEEP_DAYS 天(默认 2=今天+昨天，防跨午夜/晚间复用)。
// 只删"日期 < cutoff"的，**绝不碰当天在用的图**。在 capture_all 开头自动跑，也可 `npm run cleanup`。

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const KEEP_DAYS = Math.max(1, parseInt(process.env.CLEANUP_KEEP_DAYS || '2', 10));

const p2 = (n) => String(n).padStart(2, '0');
const ymd = (d) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const cutoff = new Date();
cutoff.setHours(0, 0, 0, 0);
cutoff.setDate(cutoff.getDate() - (KEEP_DAYS - 1)); // 保留 [cutoff, 今天]
const cutoffStr = ymd(cutoff);
const isOld = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s) && s < cutoffStr;

let removed = 0;
const log = [];

// 1) inbox 日期夹
const inbox = path.join(REPO_ROOT, 'data_sources', 'inbox');
if (fs.existsSync(inbox)) {
  for (const name of fs.readdirSync(inbox)) {
    const full = path.join(inbox, name);
    if (fs.statSync(full).isDirectory() && isOld(name)) {
      fs.rmSync(full, { recursive: true, force: true });
      removed++; log.push(`inbox/${name}/`);
    }
  }
}

// 2) blockbeats 快讯卡(文件名前缀 YYYY-MM-DD)
const bb = path.join(REPO_ROOT, 'outputs', 'blockbeats');
if (fs.existsSync(bb)) {
  for (const f of fs.readdirSync(bb)) {
    const m = f.match(/^(\d{4}-\d{2}-\d{2})/);
    if (m && isOld(m[1])) {
      fs.rmSync(path.join(bb, f), { force: true });
      removed++; log.push(`blockbeats/${f}`);
    }
  }
}

console.log(`[cleanup] 保留最近 ${KEEP_DAYS} 天(cutoff=${cutoffStr})，已删 ${removed} 项` + (removed ? `：${log.slice(0, 6).join(', ')}${log.length > 6 ? ` …+${log.length - 6}` : ''}` : ''));
process.exit(0);
