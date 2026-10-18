// The Apple-like look (as .streamlit/config.toml): Inter, Apple blue, a light grey page (black in
// dark mode) with white (dark grey) cards, pill buttons.
import { Button, Menu, Modal, Popover, Tooltip, createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core'

const apple: MantineColorsTuple = ['#e6f1fd', '#cce3fb', '#99c7f7', '#66abf3', '#338fef', '#0a84ff', '#0071e3', '#0062c4',
  '#0052a5', '#004386']
// Mantine's dark greys as Apple's: dark-7 is the card colour, dark-0 the text
const dark: MantineColorsTuple = ['#f5f5f7', '#c7c7cc', '#98989d', '#636366', '#48484a', '#3a3a3c', '#2c2c2e', '#1c1c1e',
  '#111113', '#000000']

export const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

export const theme = createTheme({
  primaryColor: 'apple',
  primaryShade: { light: 6, dark: 5 },
  colors: { apple, dark },
  fontFamily: FONT,
  headings: { fontFamily: FONT, fontWeight: '700' },
  defaultRadius: 'md',
  cursorType: 'pointer',
  components: {
    Button: Button.extend({ defaultProps: { radius: 'xl' } }),
    Modal: Modal.extend({ defaultProps: { radius: 'lg', centered: true, overlayProps: { backgroundOpacity: 0.35, blur: 2 } } }),
    Menu: Menu.extend({ defaultProps: { radius: 'md', shadow: 'md' } }),
    Popover: Popover.extend({ defaultProps: { radius: 'lg', shadow: 'md' } }),
    Tooltip: Tooltip.extend({ defaultProps: { multiline: true, maw: 320, openDelay: 300 } }),
  },
})

export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    '--mantine-color-body': '#ffffff',
    '--mantine-color-text': '#1d1d1f',
    '--mantine-color-dimmed': '#6e6e73',
    '--mantine-color-default-border': '#d2d2d7',
    '--app-page-bg': '#f5f5f7',
  },
  dark: {
    '--mantine-color-body': '#1c1c1e',
    '--mantine-color-text': '#f5f5f7',
    '--mantine-color-dimmed': '#98989d',
    '--mantine-color-default-border': '#38383a',
    '--app-page-bg': '#000000',
  },
})
