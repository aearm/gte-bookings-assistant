// Small line icons (24×24, drawn in the text colour), so no icon library is needed.
import type { ReactNode, SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function icon(paths: ReactNode, displayName: string) {
  const Icon = ({ size = 18, ...rest }: IconProps) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {paths}
    </svg>
  )
  Icon.displayName = displayName
  return Icon
}

export const IconLock = icon(<><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>, 'IconLock')
export const IconPlus = icon(<path d="M12 5v14M5 12h14" />, 'IconPlus')
export const IconDashboard = icon(<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
  <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>, 'IconDashboard')
export const IconChat = icon(<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />, 'IconChat')
export const IconBook = icon(<><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14z" />
  <path d="M6.5 17A2.5 2.5 0 0 0 4 19.5 2.5 2.5 0 0 0 6.5 22H20v-5" /></>, 'IconBook')
export const IconCube = icon(<><path d="M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z" /><path d="M3.5 7.25L12 12l8.5-4.75M12 12v9.5" /></>, 'IconCube')
export const IconSettings = icon(<><circle cx="12" cy="12" r="3" />
  <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></>, 'IconSettings')
export const IconUsage = icon(<><path d="M3 3v18h18" /><path d="M7 15l4-4 3 3 5-6" /></>, 'IconUsage')
export const IconCalendar = icon(<><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>, 'IconCalendar')
export const IconCompare = icon(<path d="M7 7h13l-3-3M17 17H4l3 3" />, 'IconCompare')
export const IconRefresh = icon(<><path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" /><path d="M4 3v5h5" />
  <path d="M4 13a8 8 0 0 0 14.6 4.5L20 16" /><path d="M20 21v-5h-5" /></>, 'IconRefresh')
export const IconMore = icon(<><circle cx="5" cy="12" r="1.4" fill="currentColor" /><circle cx="12" cy="12" r="1.4" fill="currentColor" />
  <circle cx="19" cy="12" r="1.4" fill="currentColor" /></>, 'IconMore')
export const IconEdit = icon(<><path d="M4 20h4L19 9l-4-4L4 16v4z" /><path d="M13.5 6.5l4 4" /></>, 'IconEdit')
export const IconPalette = icon(<><path d="M12 3a9 9 0 0 0 0 18c1 0 1.5-.8 1.5-1.6 0-.9-.6-1.4-.6-2.2 0-1 .8-1.7 1.8-1.7H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z" />
  <circle cx="7.5" cy="10.5" r=".9" fill="currentColor" /><circle cx="10.5" cy="7" r=".9" fill="currentColor" />
  <circle cx="15" cy="7.5" r=".9" fill="currentColor" /></>, 'IconPalette')
export const IconSend = icon(<><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>, 'IconSend')
export const IconArrowUp = icon(<path d="M12 19V5M5 12l7-7 7 7" />, 'IconArrowUp')
export const IconArrowDown = icon(<path d="M12 5v14M19 12l-7 7-7-7" />, 'IconArrowDown')
export const IconTrash = icon(<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" />, 'IconTrash')
export const IconLogout = icon(<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />, 'IconLogout')
export const IconShield = icon(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>, 'IconShield')
export const IconChevronLeft = icon(<path d="M15 18l-6-6 6-6" />, 'IconChevronLeft')
export const IconChevronRight = icon(<path d="M9 18l6-6-6-6" />, 'IconChevronRight')
export const IconAlert = icon(<><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  <path d="M12 9v4M12 17h.01" /></>, 'IconAlert')
export const IconNewDashboard = icon(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" />
  <rect x="3" y="14" width="7" height="7" rx="1.5" /><path d="M17.5 14v7M14 17.5h7" /></>, 'IconNewDashboard')
