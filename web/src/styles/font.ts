// Links the Inter font (as the Streamlit app's theme does). Pages show at once in the system font
// and switch when Inter has loaded (display=swap); without internet access the system font stays.
const HREF = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'

export function linkInterFont(): void {
  if (typeof document === 'undefined' || document.querySelector(`link[href="${HREF}"]`)) return
  for (const [rel, href, cross] of [['preconnect', 'https://fonts.googleapis.com', false],
    ['preconnect', 'https://fonts.gstatic.com', true], ['stylesheet', HREF, false]] as const) {
    const link = document.createElement('link')
    link.rel = rel
    link.href = href
    if (cross) link.crossOrigin = 'anonymous'
    document.head.appendChild(link)
  }
}
