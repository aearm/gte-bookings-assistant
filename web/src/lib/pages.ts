// The pages other than dashboards load in their own files when first opened (App.tsx). The menu
// starts loading a page's file when the pointer moves onto its link.
export const pageLoaders = {
  chat: () => import('../pages/ChatPage'),
  glossary: () => import('../pages/admin/GlossaryPage'),
  cubes: () => import('../pages/admin/CubesPage'),
  settings: () => import('../pages/admin/SettingsPage'),
  usage: () => import('../pages/admin/UsagePage'),
}

export type PageName = keyof typeof pageLoaders

export function preloadPage(name: PageName): void {
  void pageLoaders[name]().catch(() => undefined)
}
