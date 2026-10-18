// A few line icons for the Chat page (no icon library is installed). 24×24 grid, currentColor.
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Icon({ size = 16, children, ...rest }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {children}
    </svg>
  )
}

export const SendIcon = (p: IconProps) => <Icon {...p}><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></Icon>
export const StopIcon = (p: IconProps) => <Icon {...p}><rect x="6" y="6" width="12" height="12" rx="2" /></Icon>
export const ChevronIcon = ({ open, ...p }: IconProps & { open?: boolean }) => (
  <Icon {...p} style={{ transition: 'transform 150ms ease', transform: open ? 'rotate(90deg)' : undefined }}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
)
export const CheckIcon = (p: IconProps) => <Icon {...p}><path d="m5 12 5 5 9-10" /></Icon>
export const AlertIcon = (p: IconProps) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 8v5" /><path d="M12 16h.01" /></Icon>
export const InfoIcon = (p: IconProps) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></Icon>
export const CompassIcon = (p: IconProps) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5z" /></Icon>
export const ChartAddIcon = (p: IconProps) => <Icon {...p}><path d="M4 20V10" /><path d="M10 20V4" /><path d="M16 20v-6" /><path d="M19 4v6" /><path d="M16 7h6" /></Icon>
export const PaletteIcon = (p: IconProps) => <Icon {...p}><path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.9-.7-1.2-.7-2s.6-1.5 1.5-1.5H17a4 4 0 0 0 4-4c0-5-4-9-9-9z" /><circle cx="7.5" cy="11" r="1" /><circle cx="10.5" cy="7" r="1" /><circle cx="15" cy="8" r="1" /></Icon>
export const CodeIcon = (p: IconProps) => <Icon {...p}><path d="m8 7-5 5 5 5" /><path d="m16 7 5 5-5 5" /></Icon>
export const DownloadIcon = (p: IconProps) => <Icon {...p}><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></Icon>
export const VerifiedIcon = (p: IconProps) => <Icon {...p}><path d="M12 3 4.5 6v5.5c0 4.5 3.2 8.3 7.5 9.5 4.3-1.2 7.5-5 7.5-9.5V6z" /><path d="m8.5 12 2.5 2.5 4.5-5" /></Icon>
export const TableIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 10h18" /><path d="M9 4v16" /></Icon>
export const DashboardIcon = (p: IconProps) => <Icon {...p}><rect x="3" y="3" width="8" height="10" rx="1.5" /><rect x="13" y="3" width="8" height="6" rx="1.5" /><rect x="13" y="11" width="8" height="10" rx="1.5" /><rect x="3" y="15" width="8" height="6" rx="1.5" /></Icon>
export const PlusIcon = (p: IconProps) => <Icon {...p}><path d="M12 5v14" /><path d="M5 12h14" /></Icon>
export const JoinIcon = (p: IconProps) => <Icon {...p}><circle cx="9" cy="12" r="5" /><circle cx="15" cy="12" r="5" /></Icon>
export const RetryIcon = (p: IconProps) => <Icon {...p}><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 5v6h-6" /></Icon>
