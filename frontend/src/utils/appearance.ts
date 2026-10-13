/**
 * 界面外观：字体大小、浅色 / 深色 / 跟随系统
 *
 * 字号只改文字，不缩放整页。整页 zoom 会把侧栏放大到超过一屏，
 * 左下角的用户就会超出屏幕。
 *
 * 风格同时落在两处：
 *   html[data-theme="light|dark"]  项目自己的变量（styles/var.css）
 *   html.dark                       Element Plus 自带的深色变量
 *
 * 偏好写在 localStorage：登录前、接口还没回来时也能立刻按上次的设置渲染。
 * 本地没有存过时按 auto 处理，即跟随系统的 prefers-color-scheme。
 * 后端仍是权威，取到之后覆盖本地值。
 */

export type FontSize = 'small' | 'normal' | 'large'
export type ThemeName = 'light' | 'dark'
export type ThemePref = ThemeName | 'auto'

const FONT_KEY = 'huiyan_font_size'
const THEME_KEY = 'huiyan_theme'
const FONT_SIZES: FontSize[] = ['small', 'normal', 'large']

const normalizeFont = (v: unknown): FontSize =>
  FONT_SIZES.includes(v as FontSize) ? (v as FontSize) : 'normal'

const normalizeThemePref = (v: unknown): ThemePref =>
  v === 'dark' || v === 'light' ? v : 'auto'

const darkQuery = (): MediaQueryList | null =>
  typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

const systemTheme = (): ThemeName => (darkQuery()?.matches ? 'dark' : 'light')

const writeLocal = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下 localStorage 可能不可写，不影响本次生效 */
  }
}

/** 落到 <html data-font-size="...">，配套样式在 styles/var.css */
export const applyFontSize = (v: unknown): FontSize => {
  const size = normalizeFont(v)
  document.documentElement.dataset.fontSize = size
  writeLocal(FONT_KEY, size)
  return size
}

let currentPref: ThemePref = 'auto'

const paintTheme = (theme: ThemeName): void => {
  const root = document.documentElement
  root.dataset.theme = theme
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

/**
 * 接收 light / dark / auto，返回实际生效的风格。
 * auto 会在系统切换深浅色时自动跟随。
 */
export const applyTheme = (v: unknown): ThemeName => {
  currentPref = normalizeThemePref(v)
  const theme = currentPref === 'auto' ? systemTheme() : currentPref
  paintTheme(theme)
  writeLocal(THEME_KEY, currentPref)
  return theme
}

export const getStoredFontSize = (): FontSize => {
  try {
    return normalizeFont(localStorage.getItem(FONT_KEY))
  } catch {
    return 'normal'
  }
}

export const getStoredTheme = (): ThemePref => {
  try {
    return normalizeThemePref(localStorage.getItem(THEME_KEY))
  } catch {
    return 'auto'
  }
}

/** 应用启动时调用，早于挂载，避免默认外观闪一下 */
export const initAppearance = (): void => {
  applyFontSize(getStoredFontSize())
  applyTheme(getStoredTheme())
  darkQuery()?.addEventListener('change', () => {
    if (currentPref === 'auto') paintTheme(systemTheme())
  })
}
