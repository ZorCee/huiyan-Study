// 回归 E2E：第 7 项深浅色、第 8 项结果页布局、相邻功能冒烟。
// 用法：node scripts/regression/e2e.mjs
// 环境变量：
//   REG_BASE         前端地址，默认 http://127.0.0.1:5199
//   REG_USER/REG_PASS  测试账号（脱敏测试库里的账号，不要填生产账号）
//   REG_RESULT_PATH  一份已公布成绩的结果页路径，如 /training/practice/workstation?id=1&view=report
// 输出：
//   ../backend/reports/regression/e2e.json   每条用例的结果
//   ../backend/reports/regression/shots/<编号>-<分辨率>.png
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(here, '../../../backend/reports/regression')
const SHOTS = resolve(OUT, 'shots')
mkdirSync(SHOTS, { recursive: true })

const BASE = process.env.REG_BASE || 'http://127.0.0.1:5199'
const USER = process.env.REG_USER || ''
const PASS = process.env.REG_PASS || ''
const RESULT_PATH = process.env.REG_RESULT_PATH || ''
const VIEWPORTS = [
  [1920, 1080],
  [1342, 854],
  [768, 1024],
]
const SMOKE = [
  ['S-01', '任务列表', '/training/home'],
  ['S-02', '审核工作台', '/training/review'],
  ['S-03', '个人中心', '/training/profile'],
  ['S-04', '菜单导航（阅片页）', '/training/reading'],
]

const results = []
function record(id, name, meta, status, actual, shots = []) {
  results.push({ id, name, ...meta, status, actual, shots })
  console.log(`${status === 'PASS' ? '✓' : status === 'BLOCKED' ? '…' : '✗'} ${id} ${name} — ${actual}`)
}

async function readTheme(page) {
  return page.evaluate(() => {
    const root = document.documentElement
    const css = getComputedStyle(root)
    return {
      theme: root.dataset.theme,
      dark: root.classList.contains('dark'),
      elBg: css.getPropertyValue('--el-bg-color').trim(),
      bodyBg: getComputedStyle(document.body).backgroundColor,
    }
  })
}

async function login(page) {
  if (!USER || !PASS) return false
  await page.goto(`${BASE}/login`)
  const teacherTab = page.getByRole('button', { name: '教师入口' })
  if (await teacherTab.count()) {
    await teacherTab.click()
  }
  await page.getByPlaceholder('账户 / 医师工号').fill(USER)
  await page.getByPlaceholder('登录密码').fill(PASS)
  await page.keyboard.press('Enter')
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 15000 }).catch(() => {})
  return !page.url().includes('/login')
}

const browser = await chromium.launch()

// ---------- 第 7 项：首次跟随系统 ----------
for (const scheme of ['light', 'dark']) {
  const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: 1342, height: 854 } })
  const page = await ctx.newPage()
  await page.goto(`${BASE}/login`)
  await page.waitForLoadState('networkidle').catch(() => {})
  const t = await readTheme(page)
  const shot = `R7-01-${scheme}.png`
  await page.screenshot({ path: resolve(SHOTS, shot) })
  const ok = t.theme === scheme && t.dark === (scheme === 'dark')
  record(`R7-01-${scheme}`, `首次进入跟随系统（系统为${scheme === 'dark' ? '深色' : '浅色'}）`, {
    pre: '清空本地存储，系统偏好为 ' + scheme,
    steps: '打开登录页，读取 html 的 data-theme、dark 类和 --el-bg-color',
    expect: `data-theme=${scheme}，Element Plus 变量随之变化`,
  }, ok ? 'PASS' : 'FAIL', JSON.stringify(t), [shot])
  await ctx.close()
}

// ---------- 第 7 项：存储值优先、刷新保持 ----------
{
  const ctx = await browser.newContext({ colorScheme: 'light', viewport: { width: 1342, height: 854 } })
  const page = await ctx.newPage()
  await page.goto(`${BASE}/login`)
  await page.evaluate(() => localStorage.setItem('huiyan_theme', 'dark'))
  await page.reload()
  await page.waitForLoadState('networkidle').catch(() => {})
  const t = await readTheme(page)
  const shot = 'R7-02-stored-dark.png'
  await page.screenshot({ path: resolve(SHOTS, shot) })
  record('R7-02', '刷新后保持已选主题（存储值优先于系统）', {
    pre: '系统为浅色，本地存储 huiyan_theme=dark',
    steps: '刷新登录页，读取主题',
    expect: 'data-theme=dark',
  }, t.theme === 'dark' ? 'PASS' : 'FAIL', JSON.stringify(t), [shot])
  await ctx.close()
}

// ---------- 需要登录的部分 ----------
const ctx = await browser.newContext({ colorScheme: 'light' })
const page = await ctx.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(e.message))
const loggedIn = await login(page)

// 第 7 项：主要页面深浅色截图（人工对比局部未变色）
for (const [id, name, path] of SMOKE) {
  if (!loggedIn) break
  for (const scheme of ['light', 'dark']) {
    await page.evaluate((s) => localStorage.setItem('huiyan_theme', s), scheme)
    await page.goto(`${BASE}${path}`)
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.screenshot({ path: resolve(SHOTS, `R7-03-${id}-${scheme}.png`), fullPage: true })
  }
}
record('R7-03', '主要页面深浅色截图（需人工核对局部未变色）', {
  pre: '已登录测试账号',
  steps: '对冒烟页面分别以浅色、深色截图',
  expect: '无白底 / 深底冲突，人工核对',
}, loggedIn ? 'MANUAL' : 'BLOCKED', loggedIn ? '已截图，待人工核对' : '未提供 REG_USER/REG_PASS',
  loggedIn ? SMOKE.flatMap(([id]) => [`R7-03-${id}-light.png`, `R7-03-${id}-dark.png`]) : [])

// 冒烟
for (const [id, name, path] of SMOKE) {
  const meta = { pre: '已登录测试账号', steps: `打开 ${path}`, expect: '页面正常渲染，无脚本错误，不跳回登录页' }
  if (!loggedIn) { record(id, name, meta, 'BLOCKED', '未提供 REG_USER/REG_PASS'); continue }
  await page.evaluate(() => localStorage.setItem('huiyan_theme', 'light'))
  errors.length = 0
  await page.goto(`${BASE}${path}`)
  await page.waitForLoadState('networkidle').catch(() => {})
  const text = (await page.evaluate(() => document.body.innerText || '')).trim()
  const shot = `${id}.png`
  await page.screenshot({ path: resolve(SHOTS, shot) })
  const ok = !page.url().includes('/login') && text.length > 20 && errors.length === 0
  record(id, name, meta, ok ? 'PASS' : 'FAIL',
    `url=${page.url()} 文本长度=${text.length} 脚本错误=${errors.length}${errors[0] ? '：' + errors[0] : ''}`, [shot])
}

// 第 8 项：结果页布局，三种分辨率
for (const [w, h] of VIEWPORTS) {
  const id = `R8-${w}x${h}`
  const meta = {
    pre: '一份已公布成绩的考试结果页',
    steps: `视口 ${w}×${h} 打开结果页，测图像区域和右侧面板的位置，检查横向溢出，点「全屏查看」再退出`,
    expect: w <= 1024 ? '上下排列，图像在上，无横向溢出' : '图像宽度大于右侧面板，两者不重叠，无横向溢出',
  }
  if (!loggedIn || !RESULT_PATH) { record(id, `结果页布局 ${w}×${h}`, meta, 'BLOCKED', '缺少登录账号或 REG_RESULT_PATH'); continue }
  await page.setViewportSize({ width: w, height: h })
  await page.goto(`${BASE}${RESULT_PATH}`)
  await page.waitForLoadState('networkidle').catch(() => {})
  await page.waitForTimeout(1500)
  const m = await page.evaluate(() => {
    const body = document.querySelector('.ws-body')
    const kids = body ? [...body.children].filter((el) => el.offsetParent !== null) : []
    const boxes = kids.map((el) => el.getBoundingClientRect())
    return {
      overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
      boxes: boxes.map((b) => ({ x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) })),
    }
  })
  const [img, side] = m.boxes
  let ok = !m.overflowX && img && side
  if (ok && w > 1024) ok = img.w > side.w && img.x + img.w <= side.x + 1
  if (ok && w <= 1024) ok = side.y >= img.y + img.h - 1
  const shot = `${id}.png`
  await page.screenshot({ path: resolve(SHOTS, shot) })
  const fsBtn = page.getByRole('button', { name: /全屏查看/ })
  let fsNote = '未找到全屏按钮'
  if (await fsBtn.count()) {
    await fsBtn.first().click()
    await page.waitForTimeout(500)
    const inFs = await page.evaluate(() => !!document.fullscreenElement)
    await page.evaluate(() => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}) })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(500)
    fsNote = `全屏=${inFs}`
  }
  record(id, `结果页布局 ${w}×${h}`, meta, ok ? 'PASS' : 'FAIL', `${JSON.stringify(m)} ${fsNote}`, [shot])
}

await browser.close()
writeFileSync(resolve(OUT, 'e2e.json'), JSON.stringify(results, null, 2))
console.log(`\n写入 ${resolve(OUT, 'e2e.json')}`)
