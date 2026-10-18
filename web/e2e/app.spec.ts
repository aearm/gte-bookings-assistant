// The app without asking Claude: dashboards (open, periods, compare, refresh), signing in, admin pages,
// managing dashboards and charts, glossary decisions. Runs against the test server (playwright.config.ts).
import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const state = () => JSON.parse(fs.readFileSync(path.join(__dirname, '.state.json'), 'utf-8'))

async function signIn(page: Page, baseURL: string) {
  await page.context().addCookies([{ name: 'ba_session', value: state().admin_token, url: baseURL }])
}

async function chartsDrawn(page: Page, timeout?: number) {
  await expect(page.locator('canvas').first()).toBeVisible({ timeout })
}

test.describe.configure({ mode: 'serial' })

test('a dashboard opens and draws its charts; opening it again is fast', async ({ page }) => {
  let t = Date.now()
  await page.goto('/')
  await expect(page.getByTestId('dashboard-title')).toHaveText('Test dashboard')
  await chartsDrawn(page, 150_000)  // the cubes run: the server holds queries while it refreshes a cube
  const first = Date.now() - t
  t = Date.now()
  await page.reload()
  await chartsDrawn(page)
  const again = Date.now() - t
  console.log(`dashboard: first open ${first} ms (runs the cubes), open again ${again} ms (saved numbers)`)
  expect(again).toBeLessThan(3000)
  await expect(page.getByTestId('period-button')).toContainText('Last 7 days')  // the default period
})

test('periods and comparison: presets, back to a period seen before, comparison off', async ({ page }) => {
  await page.goto('/')
  await chartsDrawn(page)
  let t = Date.now()
  const fresh = page.waitForResponse((r) => r.url().includes('/results?') && r.url().includes('preset=This'))
  await page.getByTestId('period-button').click()
  await page.getByTestId('period-panel').getByRole('button', { name: /^This month/ }).click()
  await expect(page).toHaveURL(/preset=This(\+|%20)month/)
  await fresh
  await expect(page.getByLabel('Loading the numbers for this period')).toHaveCount(0)
  await chartsDrawn(page)
  console.log(`period change to a period not seen before (the cubes run): ${Date.now() - t} ms`)
  t = Date.now()
  await page.getByTestId('period-button').click()
  await page.getByTestId('period-panel').getByRole('button', { name: /^Last 7 days/ }).click()
  await expect(page.getByTestId('period-button')).toContainText('Last 7 days')
  await chartsDrawn(page)
  console.log(`period change back to a period seen before: ${Date.now() - t} ms`)
  await page.getByTestId('compare-button').click()
  await page.getByTestId('compare-panel').getByRole('radio', { name: /^No comparison/ }).click()
  await expect(page.getByTestId('compare-button')).toHaveText(/^Compare$/)  // applied at once: no comparison
  await page.getByTestId('refresh').click()
  await chartsDrawn(page)
})

test('signing in opens the admin pages; signing out locks them again', async ({ page, baseURL }) => {
  await page.goto('/cubes')
  await expect(page.getByTestId('admin-locked')).toBeVisible()
  await signIn(page, baseURL!)
  await page.goto('/cubes')
  await expect(page.getByTestId('cube-status-table')).toBeVisible()
  await page.goto('/settings')
  await expect(page.getByTestId('api-key-status')).toBeVisible()
  await expect(page.locator('body')).not.toContainText('sk-ant-')  // a key is never shown
  await page.goto('/usage')
  await expect(page.getByTestId('usage-summary').or(page.getByTestId('usage-empty')).first()).toBeVisible()  // no usage yet in the test folder
  await page.getByTestId('admin-pill').click()
  await page.getByTestId('sign-out').click()
  await page.goto('/cubes')
  await expect(page.getByTestId('admin-locked')).toBeVisible()
})

test('dashboards: new, rename, delete', async ({ page, baseURL }) => {
  await signIn(page, baseURL!)
  await page.goto('/')
  await page.getByTestId('nav-new-dashboard').click()
  await page.getByRole('dialog', { name: 'New dashboard' }).getByLabel('Name').fill('E2E board')
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByTestId('dashboard-title')).toHaveText('E2E board')
  await page.getByTestId('dashboard-menu').click()
  await page.getByRole('menuitem', { name: /Rename/ }).click()
  await page.getByRole('dialog', { name: 'Rename dashboard' }).getByLabel('Name').fill('E2E board renamed')
  await page.getByRole('dialog', { name: 'Rename dashboard' }).getByRole('button', { name: 'Save' }).click()
  await expect(page.getByTestId('dashboard-title')).toHaveText('E2E board renamed')
  await page.getByTestId('dashboard-menu').click()
  await page.getByRole('menuitem', { name: /Delete dashboard/ }).click()
  await page.getByTestId('confirm-delete-dashboard').click()
  await expect(page.getByRole('link', { name: 'E2E board renamed' })).toHaveCount(0)
})

test('charts: edit the title, send a copy to a new dashboard, delete the copy', async ({ page, baseURL }) => {
  await signIn(page, baseURL!)
  await page.goto('/')
  await chartsDrawn(page)
  const menu = page.locator('[data-testid^="chart-menu-"]').first()
  await menu.click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  await page.getByLabel('Title').fill('Edited by the test')
  await page.getByRole('dialog').getByRole('button', { name: /Save/ }).click()
  await expect(page.getByText('Edited by the test').first()).toBeVisible()
  await page.reload()
  await expect(page.getByText('Edited by the test').first()).toBeVisible()  // saved
  await page.locator('[data-testid^="chart-menu-"]').first().click()
  await page.getByRole('menuitem', { name: 'Send to another dashboard' }).click()
  const dialog = page.getByRole('dialog', { name: 'Send to another dashboard' })
  await dialog.getByLabel('Dashboard').first().click()
  await page.getByRole('option', { name: /New dashboard/ }).click()
  await dialog.getByLabel('Name of the new dashboard').fill('E2E copies')
  await dialog.getByRole('button', { name: 'Send' }).click()
  await page.getByRole('link', { name: 'E2E copies' }).click()
  await expect(page.getByText('Edited by the test').first()).toBeVisible()
  await page.locator('[data-testid^="chart-menu-"]').first().click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.getByTestId('confirm-delete-chart').click()
  await expect(page.getByTestId('empty-dashboard')).toBeVisible()
})

// Chat without Claude: the browser answers the conversation's requests itself (the cube server and Claude
// are never asked), holding an answer back to see what the page does meanwhile.
const sse = (events: [string, unknown][]) => events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join('')
const answered = {
  id: 'e2e-t1', question: 'Bookings by month', understanding: 'Bookings per month', query: 'EVALUATE ...', cubes: [],
  explanation: '', notes: [], periods: [], clarify: null, error: null, answer_id: null,
  table: { columns: [{ name: 'Month', type: 'text' }, { name: 'Bookings', type: 'number' }], rows: [['Jan', 3], ['Feb', 5]], row_count: 2, truncated: false },
  chart: { kind: 'bar', title: 'Bookings by month', summary: 'Bookings grew from January to February.', note: '',
           option: { xAxis: { type: 'category', data: ['Jan', 'Feb'] }, yAxis: { type: 'value' }, series: [{ type: 'bar', data: [3, 5] }] } },
}

async function chatReady(page: Page) { // questions can be asked (the test server may have no data layer)
  await page.route('**/api/info', async route => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), ready: true, why: '' } })
  })
}

test('chat: an answer on its way keeps arriving while another page is open', async ({ page }) => {
  await chatReady(page)
  await page.route('**/api/conversations', route => route.fulfill({ json: { id: 'e2e-conv' } }))
  let held: import('@playwright/test').Route | undefined
  const asked = new Promise<void>(resolve => {
    void page.route('**/api/conversations/e2e-conv/ask', route => { held = route; resolve() })
  })
  await page.goto('/chat')
  await page.getByTestId('chat-ask').fill('Bookings by month')
  await page.getByTestId('chat-send').click()
  await asked
  await expect(page.getByTestId('chat-turn')).toHaveAttribute('data-status', 'streaming')

  await page.getByRole('link', { name: 'Test dashboard' }).click()  // away while Claude is still answering
  await expect(page.getByTestId('dashboard-title')).toHaveText('Test dashboard')
  await held!.fulfill({
    status: 200, headers: { 'content-type': 'text/event-stream' },
    body: sse([['step', { text: 'Understanding the question' }], ['data', { table: answered.table }],
               ['chart', { chart: answered.chart }], ['done', { turn: answered }]]),
  })
  await page.getByRole('link', { name: 'Chat', exact: true }).click()
  await expect(page.getByTestId('chat-question')).toHaveText('Bookings by month')
  await expect(page.getByTestId('chat-turn')).toHaveAttribute('data-status', 'done')
  await expect(page.getByTestId('chat-summary')).toContainText('Bookings grew from January to February.')
  await expect(page.getByTestId('chat-stopped')).toHaveCount(0)
})

test('chat: after a reload, a question still being answered shows, then its answer', async ({ page }) => {
  await chatReady(page)
  await page.addInitScript(() => sessionStorage.setItem('chat.conversations', JSON.stringify({ '': 'e2e-conv2' })))
  let ready = false
  await page.route('**/api/conversations/e2e-conv2', route => route.fulfill({
    json: ready ? { id: 'e2e-conv2', scope: '', turns: [answered], pending: null }
                : { id: 'e2e-conv2', scope: '', turns: [], pending: { question: 'Bookings by month', steps: ['Understanding the question'] } },
  }))
  await page.goto('/chat')
  await expect(page.getByTestId('chat-question')).toHaveText('Bookings by month')
  await expect(page.getByTestId('chat-turn')).toHaveAttribute('data-status', 'streaming')
  ready = true  // the server has finished it
  await expect(page.getByTestId('chat-turn')).toHaveAttribute('data-status', 'done', { timeout: 15_000 })
  await expect(page.getByTestId('chat-summary')).toContainText('Bookings grew from January to February.')
})

// The dashboards the app ships with, on the real cubes: every chart drawn, none failing.
async function allDrawn(page: Page) {
  await page.waitForFunction(() => {
    const cards = document.querySelectorAll('.chart-card, .kpi')
    return cards.length > 0 && [...cards].every(c => !c.querySelector('.mantine-Skeleton-root'))
      && !document.querySelector('[aria-label="Loading the numbers for this period"]')
  }, null, { timeout: 170_000, polling: 250 })
}

for (const [id, name] of [['overview', 'Business overview'], ['market', 'Market view'],
                          ['destination', 'Destination view'], ['client', 'Client view'],
                          ['supplier', 'Supplier view']]) {
  test(`built-in dashboard: ${name} draws every chart`, async ({ page }) => {
    const t = Date.now()
    await page.goto(`/dashboard/${id}`)
    await expect(page.getByTestId('dashboard-title')).toHaveText(name)
    await allDrawn(page)
    console.log(`${name}: ${await page.locator('.chart-card, .kpi').count()} charts in ${Date.now() - t} ms`)
    await expect(page.locator('.kpi')).toHaveCount(8)
    await expect(page.getByTestId('error-note')).toHaveCount(0)
    if (id !== 'overview') await expect(page.getByTestId(`filter-${id}`)).not.toHaveValue('') // the default picked
  })
}

test('built-in dashboard: picking another client redraws the Client view for it', async ({ page }) => {
  await page.goto('/dashboard/client')
  await allDrawn(page)
  const picker = page.getByTestId('filter-client')
  const before = await picker.inputValue()
  await picker.click()
  const second = page.getByRole('option').nth(1)  // the second biggest client (no name written here)
  const label = (await second.textContent())!.trim()
  const asked = page.waitForResponse(r => r.url().includes('/results?') && r.url().includes('f_client='))
  await second.click()
  await asked
  await expect(page).toHaveURL(/f_client=/)
  await expect(picker).toHaveValue(label)
  expect(label).not.toBe(before)
  await allDrawn(page)
  await expect(page.getByTestId('error-note')).toHaveCount(0)
})

test('glossary: an admin agrees to a decision', async ({ page, baseURL }) => {
  await signIn(page, baseURL!)
  await page.goto('/glossary')
  const agree = page.locator('[data-testid^="decision-agree-"]').first()
  await expect(agree).toBeVisible()
  const id = (await agree.getAttribute('data-testid'))!.replace('decision-agree-', '')
  await agree.click()
  await expect(page.getByTestId(`decision-${id}`)).toContainText(/Agreed/i)
})
