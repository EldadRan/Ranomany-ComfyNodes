// Internationalization module for the camera widget
const { app } = window.comfyAPI.app

export type Locale = 'en' | 'zh' | 'ja' | 'ko'

export interface Translations {
  // Dropdown labels
  horizontal: string
  vertical: string
  zoom: string
  // Info panel labels
  horizontalFull: string
  verticalFull: string
  zoomFull: string
  // Reset button
  resetToDefaults: string
  // Azimuth options (8 zones)
  frontView: string
  frontRightQuarterView: string
  rightSideView: string
  backRightQuarterView: string
  backView: string
  backLeftQuarterView: string
  leftSideView: string
  frontLeftQuarterView: string
  // Elevation options (6 zones)
  lowAngleShot: string
  slightLowAngle: string
  eyeLevelShot: string
  slightHighAngle: string
  highAngleShot: string
  overheadHighAngleShot: string
  // Distance options (8 zones)
  extremeWideShot: string
  wideShot: string
  fullShot: string
  mediumLongShot: string
  mediumShot: string
  closeUp: string
  extremeCloseUp: string
  macroShot: string
}

const translations: Record<Locale, Translations> = {
  en: {
    // Dropdown labels
    horizontal: 'H',
    vertical: 'V',
    zoom: 'Z',
    // Info panel labels
    horizontalFull: 'Horizontal',
    verticalFull: 'Vertical',
    zoomFull: 'Zoom',
    // Reset button
    resetToDefaults: 'Reset to defaults',
    // Azimuth options
    frontView: 'front view',
    frontRightQuarterView: 'front-right three-quarter angle',
    rightSideView: 'right side profile',
    backRightQuarterView: 'rear-right three-quarter angle',
    backView: 'rear view',
    backLeftQuarterView: 'rear-left three-quarter angle',
    leftSideView: 'left side profile',
    frontLeftQuarterView: 'front-left three-quarter angle',
    // Elevation options
    lowAngleShot: 'low-angle shot',
    slightLowAngle: 'slight low angle',
    eyeLevelShot: 'eye-level shot',
    slightHighAngle: 'slight high angle',
    highAngleShot: 'high-angle shot',
    overheadHighAngleShot: 'overhead high-angle shot',
    // Distance options
    extremeWideShot: 'extreme wide shot',
    wideShot: 'wide shot',
    fullShot: 'full shot',
    mediumLongShot: 'medium long shot',
    mediumShot: 'medium shot',
    closeUp: 'close-up',
    extremeCloseUp: 'extreme close-up',
    macroShot: 'macro shot'
  },
  zh: {
    // Dropdown labels
    horizontal: '水平',
    vertical: '垂直',
    zoom: '距离',
    // Info panel labels
    horizontalFull: '水平角度',
    verticalFull: '垂直角度',
    zoomFull: '距离',
    // Reset button
    resetToDefaults: '重置为默认值',
    // Azimuth options
    frontView: '正面视角',
    frontRightQuarterView: '右前方视角',
    rightSideView: '右侧视角',
    backRightQuarterView: '右后方视角',
    backView: '背面视角',
    backLeftQuarterView: '左后方视角',
    leftSideView: '左侧视角',
    frontLeftQuarterView: '左前方视角',
    // Elevation options
    lowAngleShot: '仰拍',
    slightLowAngle: '轻微仰角',
    eyeLevelShot: '平视',
    slightHighAngle: '轻微俯角',
    highAngleShot: '俯拍',
    overheadHighAngleShot: '顶部俯拍',
    // Distance options
    extremeWideShot: '超远景',
    wideShot: '远景',
    fullShot: '全景',
    mediumLongShot: '中远景',
    mediumShot: '中景',
    closeUp: '特写',
    extremeCloseUp: '大特写',
    macroShot: '微距'
  },
  ja: {
    // Dropdown labels
    horizontal: '水平',
    vertical: '垂直',
    zoom: '距離',
    // Info panel labels
    horizontalFull: '水平角度',
    verticalFull: '垂直角度',
    zoomFull: '距離',
    // Reset button
    resetToDefaults: 'デフォルトにリセット',
    // Azimuth options
    frontView: '正面',
    frontRightQuarterView: '右前方',
    rightSideView: '右側面',
    backRightQuarterView: '右後方',
    backView: '背面',
    backLeftQuarterView: '左後方',
    leftSideView: '左側面',
    frontLeftQuarterView: '左前方',
    // Elevation options
    lowAngleShot: 'ローアングル',
    slightLowAngle: 'やや下から',
    eyeLevelShot: 'アイレベル',
    slightHighAngle: 'やや上から',
    highAngleShot: 'ハイアングル',
    overheadHighAngleShot: '俯瞰',
    // Distance options
    extremeWideShot: 'エクストリームワイド',
    wideShot: 'ワイドショット',
    fullShot: 'フルショット',
    mediumLongShot: 'ミディアムロング',
    mediumShot: 'ミディアムショット',
    closeUp: 'クローズアップ',
    extremeCloseUp: 'エクストリームクローズアップ',
    macroShot: 'マクロ'
  },
  ko: {
    // Dropdown labels
    horizontal: '수평',
    vertical: '수직',
    zoom: '거리',
    // Info panel labels
    horizontalFull: '수평 각도',
    verticalFull: '수직 각도',
    zoomFull: '거리',
    // Reset button
    resetToDefaults: '기본값으로 재설정',
    // Azimuth options
    frontView: '정면',
    frontRightQuarterView: '우측 전방',
    rightSideView: '우측면',
    backRightQuarterView: '우측 후방',
    backView: '후면',
    backLeftQuarterView: '좌측 후방',
    leftSideView: '좌측면',
    frontLeftQuarterView: '좌측 전방',
    // Elevation options
    lowAngleShot: '로우 앵글',
    slightLowAngle: '약한 로우 앵글',
    eyeLevelShot: '아이 레벨',
    slightHighAngle: '약한 하이 앵글',
    highAngleShot: '하이 앵글',
    overheadHighAngleShot: '부감 (오버헤드)',
    // Distance options
    extremeWideShot: '익스트림 와이드 샷',
    wideShot: '와이드 샷',
    fullShot: '풀 샷',
    mediumLongShot: '미디엄 롱 샷',
    mediumShot: '미디엄 샷',
    closeUp: '클로즈업',
    extremeCloseUp: '익스트림 클로즈업',
    macroShot: '매크로 샷'
  }
}

let currentLocale: Locale = 'en'

/**
 * Detect locale from ComfyUI settings or browser
 */
export function detectLocale(): Locale {
  console.log('[QwenMultiangle i18n] Detecting locale...')

  // Try to get locale from ComfyUI settings API
  try {
    const comfyLocale = app.ui?.settings?.getSettingValue?.('Comfy.Locale')
    console.log('[QwenMultiangle i18n] ComfyUI locale from app.ui.settings:', comfyLocale)

    if (comfyLocale) {
      const localeStr = String(comfyLocale).toLowerCase()
      // If ComfyUI has a locale setting, use it (don't fall back to browser)
      if (localeStr.startsWith('zh')) {
        console.log('[QwenMultiangle i18n] Using Chinese (from ComfyUI setting)')
        return 'zh'
      }
      if (localeStr.startsWith('ja')) {
        console.log('[QwenMultiangle i18n] Using Japanese (from ComfyUI setting)')
        return 'ja'
      }
      if (localeStr.startsWith('ko')) {
        console.log('[QwenMultiangle i18n] Using Korean (from ComfyUI setting)')
        return 'ko'
      }
      // Any other locale (en, fr, de, etc.) defaults to English
      console.log('[QwenMultiangle i18n] Using English (from ComfyUI setting)')
      return 'en'
    }
  } catch (e) {
    console.log('[QwenMultiangle i18n] Error getting ComfyUI locale:', e)
  }

  // Only fall back to browser language if ComfyUI locale is not set
  const browserLang = navigator.language || (navigator as unknown as { userLanguage?: string }).userLanguage || 'en'
  console.log('[QwenMultiangle i18n] Browser language:', browserLang)

  if (browserLang.startsWith('zh')) {
    console.log('[QwenMultiangle i18n] Using Chinese (from browser)')
    return 'zh'
  }
  if (browserLang.startsWith('ja')) {
    console.log('[QwenMultiangle i18n] Using Japanese (from browser)')
    return 'ja'
  }
  if (browserLang.startsWith('ko')) {
    console.log('[QwenMultiangle i18n] Using Korean (from browser)')
    return 'ko'
  }

  console.log('[QwenMultiangle i18n] Using English (default)')
  return 'en'
}

/**
 * Initialize i18n with auto-detected locale
 */
export function initI18n(): void {
  currentLocale = detectLocale()
}

/**
 * Get current locale
 */
export function getLocale(): Locale {
  return currentLocale
}

/**
 * Set locale manually
 */
export function setLocale(locale: Locale): void {
  currentLocale = locale
}

/**
 * Get translation for a key
 */
export function t(key: keyof Translations): string {
  return translations[currentLocale][key] || translations.en[key] || key
}

/**
 * Get all translations for current locale
 */
export function getTranslations(): Translations {
  return translations[currentLocale]
}

// Initialize on module load
initI18n()
