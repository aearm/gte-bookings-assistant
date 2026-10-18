import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import './styles/app.css'
import App from './App'
import { prefetchStartup } from './lib/queries'
import { cssVariablesResolver, theme } from './styles/theme'
import { linkInterFont } from './styles/font'

// Results stay fresh for a minute and are kept for 30: going back to a page shows it at once.
const queries = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, gcTime: 30 * 60_000, retry: 1 } } })
prefetchStartup(queries) // session, defaults and the menu are on their way before the first draw
linkInterFont()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} cssVariablesResolver={cssVariablesResolver} defaultColorScheme="auto">
      <Notifications position="bottom-right" />
      <QueryClientProvider client={queries}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
)
