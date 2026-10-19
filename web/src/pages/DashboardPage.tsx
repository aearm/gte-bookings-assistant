// One dashboard: its charts for the period picked at the top (a quick choice, days or ISO weeks),
// compared with another period if wanted. Saved numbers show at once; while charts are brought up
// to date in the background the page asks again every 3 s. "/" opens the first dashboard.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ActionIcon, Button, Group, Loader, Skeleton, Tooltip } from '@mantine/core'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { DashboardResults } from '../api/types'
import { preloadECharts } from '../charts/EChart'
import { useSession } from '../components/auth/useSession'
import ChartCard from '../components/dashboard/ChartCard'
import ComparePicker from '../components/dashboard/ComparePicker'
import DashboardFilters from '../components/dashboard/DashboardFilters'
import DashboardMenu from '../components/dashboard/DashboardMenu'
import KpiCard from '../components/dashboard/KpiCard'
import PeriodPicker from '../components/dashboard/PeriodPicker'
import { chartSource } from '../components/dashboard/cardText'
import type { CardAction } from '../components/dashboard/ChartMenu'
import { placeCharts } from '../components/dashboard/layout'
import AddChartDialog from '../components/dashboard/dialogs/AddChartDialog'
import { DeleteChartDialog, RestyleDialog, SendDialog } from '../components/dashboard/dialogs/ChartDialogs'
import { DeleteDashboardDialog, RenameDashboardDialog } from '../components/dashboard/dialogs/DashboardDialogs'
import EditChartDialog from '../components/dashboard/dialogs/EditChartDialog'
import ErrorNote from '../components/ErrorNote'
import { IconPlus, IconRefresh } from '../components/icons'
import { useDashboardActions } from '../lib/dashboardActions'
import { cubeLabeller } from '../lib/labels'
import { errorDetails, errorText, notifyError } from '../lib/notify'
import { datesText, todayIso } from '../lib/periods'
import {
  compareDates, customRange, readCompare, readFilters, readPeriod, resultsParams, writeFilter, writeSearch,
  type CompareChoice, type PeriodChoice,
} from '../lib/periodState'
import { dashboardQuery, dashboardsQuery, fetchResults, infoQuery, resultsKey } from '../lib/queries'
import { useUiStore } from '../lib/uiStore'
import { usePeriodStore } from '../lib/usePeriodStore'

preloadECharts() // the chart library loads alongside the dashboard's numbers

export default function DashboardPage() {
  const { id: routeId } = useParams()
  const boards = useQuery(dashboardsQuery)
  const id = routeId ?? boards.data?.[0]?.id
  if (id) return <DashboardView key={id} id={id} />
  if (boards.isError) {
    return <div className="app-page"><ErrorNote message={errorText(boards.error)} details={errorDetails(boards.error)} /></div>
  }
  if (boards.data) return <NoDashboards />
  return <div className="app-page" data-testid="DashboardPage"><Skeleton height={36} width={280} radius="md" /></div>
}

function NoDashboards() {
  const openNew = useUiStore((s) => s.openNewDashboard)
  return (
    <div className="app-page" data-testid="DashboardPage">
      <div className="panel">
        <h2 style={{ marginTop: 0 }}>No dashboards yet</h2>
        <p className="dash-caption" style={{ marginLeft: 0 }}>
          Make one here, or ask a question in Chat and keep the answer on a dashboard.
        </p>
        <Button leftSection={<IconPlus size={16} />} onClick={openNew}>New dashboard</Button>
      </div>
    </div>
  )
}

type Dialog = { kind: 'add' | 'rename' | 'delete-board' } | CardAction | null

function DashboardView({ id }: { id: string }) {
  const client = useQueryClient()
  const { isAdmin } = useSession()
  const info = useQuery(infoQuery)
  const board = useQuery(dashboardQuery(id))
  const actions = useDashboardActions()
  const [search, setSearch] = useSearchParams()
  const setStoredSearch = usePeriodStore((s) => s.setSearch)
  const today = todayIso()

  // the period and comparison: from the address, else the defaults of /api/info
  const defaults = info.data?.defaults
  const period = useMemo(() => readPeriod(search, defaults, today), [search, defaults, today])
  const compare = useMemo(() => readCompare(search, defaults), [search, defaults])
  const filterDefs = board.data?.filters
  const filterKeys = useMemo(() => (filterDefs ?? []).map((f) => f.key), [filterDefs])
  const picked = useMemo(() => readFilters(search, filterKeys), [search, filterKeys])
  const params = useMemo(() => resultsParams(period, compare, picked), [period, compare, picked])
  useEffect(() => { if (search.toString()) setStoredSearch(search.toString()) }, [search, setStoredSearch])

  const results = useQuery<DashboardResults>({
    queryKey: resultsKey(id, params),
    queryFn: () => fetchResults(id, params),
    // the defaults decide the first period, the dashboard which filters it has
    enabled: (info.isSuccess || info.isError) && (board.isSuccess || board.isError),
    placeholderData: keepPreviousData, // the last numbers stay while a new period loads
    refetchInterval: (q) => (q.state.data?.updating ? 3000 : false),
  })

  const choosePeriod = useCallback((p: PeriodChoice) => setSearch(writeSearch(p, compare, search), { replace: true }),
    [compare, search, setSearch])
  const chooseCompare = useCallback((c: CompareChoice) => setSearch(writeSearch(period, c, search), { replace: true }),
    [period, search, setSearch])
  const chooseFilter = useCallback((key: string, value: string) => setSearch(writeFilter(search, key, value), { replace: true }),
    [search, setSearch])

  const [refreshing, setRefreshing] = useState(false)
  const refresh = async () => {
    setRefreshing(true)
    try {
      client.setQueryData(resultsKey(id, params), await fetchResults(id, params, true))
    } catch (error) {
      notifyError(error, 'The latest numbers could not be loaded')
    } finally {
      setRefreshing(false)
    }
  }

  const [dialog, setDialog] = useState<Dialog>(null)
  const closeDialog = useCallback(() => setDialog(null), [])
  const onAction = useCallback((action: CardAction) => {
    if (action.kind === 'up' || action.kind === 'down') {
      actions.moveChart(id, action.chart.id, action.kind === 'up' ? -1 : 1).catch((e) => notifyError(e))
    } else {
      setDialog(action)
    }
  }, [actions, id])
  const chartFor = (kind: CardAction['kind']) => (dialog && 'chart' in dialog && dialog.kind === kind ? dialog.chart : null)

  if (board.isError) return <MissingDashboard error={board.error} />

  const charts = board.data?.charts ?? []
  const cubeLabel = cubeLabeller(info.data)
  const boardCubes = new Set(charts.flatMap((c) => c.cubes))
  const several = boardCubes.size > 1
  const kpis = charts.filter((c) => c.chart_type === 'kpi')
  const { cards, tileSpan } = placeCharts(charts.filter((c) => c.chart_type !== 'kpi'))
  const shownCompare = compareDates(compare.mode, period, customRange(compare))
  const compareText = shownCompare ? datesText(...shownCompare) : ''
  const data = results.data
  const setup = data?.setup ?? ''
  const loadingNewPeriod = results.isFetching && results.isPlaceholderData
  const openAdd = () => setDialog({ kind: 'add' })

  return (
    <div className="app-page" data-testid="DashboardPage">
      <div className="dash-head">
        {board.data ? <h1 className="dash-title" data-testid="dashboard-title">{board.data.name}</h1>
          : <Skeleton height={36} width={280} radius="md" />}
        <Group gap="xs">
          <Button leftSection={<IconPlus size={16} />} onClick={openAdd} data-testid="add-chart">Add chart</Button>
          <DashboardMenu isAdmin={isAdmin} onRename={() => setDialog({ kind: 'rename' })}
                         onDelete={() => setDialog({ kind: 'delete-board' })} />
        </Group>
      </div>

      <div className="dash-filters">
        {filterDefs?.length ? (
          <DashboardFilters dashboardId={id} filters={filterDefs} picked={picked} used={results.data?.filters}
                            onChange={chooseFilter} />
        ) : null}
        <PeriodPicker value={period} today={today} onChange={choosePeriod} />
        <ComparePicker period={period} value={compare} today={today} onChange={chooseCompare} />
        <Tooltip label="Get the latest numbers from the server">
          <ActionIcon variant="subtle" size="lg" radius="xl" onClick={refresh} loading={refreshing} aria-label="Refresh"
                      data-testid="refresh">
            <IconRefresh size={18} />
          </ActionIcon>
        </Tooltip>
        {loadingNewPeriod && <Loader size="xs" aria-label="Loading the numbers for this period" />}
        <DataUpdated results={data} cubeLabel={cubeLabel} />
      </div>

      {data?.updating && (
        <div className="dash-updating" data-testid="updating">
          <IconRefresh size={14} className="spin" /> Showing the last numbers while the latest load…
        </div>
      )}
      {setup && (
        <div className="panel dash-setup" data-testid="setup-note">
          {setup}{' '}
          {isAdmin ? <Link to="/settings">Open Settings</Link> : 'Ask an admin to set it up.'}
        </div>
      )}
      {results.isError && !data && (
        <div style={{ marginBottom: 16 }}>
          <ErrorNote title="The numbers could not be loaded" message={errorText(results.error)} details={errorDetails(results.error)} />
        </div>
      )}

      {board.data && !charts.length ? (
        <EmptyDashboard onAdd={openAdd} />
      ) : (
        <>
          {kpis.length > 0 && (
            <div className={`kpi-row${kpis.length % 4 === 0 ? ' kpi-row--fours' : ''}`}>
              {kpis.map((c) => (
                <KpiCard key={c.id} chart={c} result={data?.charts[c.id]} isAdmin={isAdmin} onAction={onAction}
                         source={chartSource(c, several, cubeLabel)} waiting={!!setup} />
              ))}
            </div>
          )}
          <div className="chart-grid">
            {cards.map(({ chart, span }) => (
              <ChartCard key={chart.id} chart={chart} result={data?.charts[chart.id]} span={span} isAdmin={isAdmin}
                         source={chartSource(chart, several, cubeLabel)} compareDates={compareText} onAction={onAction}
                         waiting={!!setup} />
            ))}
            {board.data && (
              <button type="button" className={`add-tile${tileSpan === 2 ? ' span-2' : ''}`} onClick={openAdd}
                      title="Describe a chart in plain English; Claude builds it from the data">
                <IconPlus size={18} /> Add chart
              </button>
            )}
          </div>
        </>
      )}

      <AddChartDialog opened={dialog?.kind === 'add'} onClose={closeDialog} dashboardId={id} />
      <EditChartDialog chart={chartFor('edit')} onClose={closeDialog} dashboardId={id} cubeLabel={cubeLabel} />
      <RestyleDialog chart={chartFor('restyle')} onClose={closeDialog} dashboardId={id} />
      <SendDialog chart={chartFor('send')} onClose={closeDialog} dashboardId={id} />
      <DeleteChartDialog chart={chartFor('delete')} onClose={closeDialog} dashboardId={id} />
      <RenameDashboardDialog board={board.data} opened={dialog?.kind === 'rename'} onClose={closeDialog} />
      <DeleteDashboardDialog board={board.data} opened={dialog?.kind === 'delete-board'} onClose={closeDialog} />
    </div>
  )
}

function EmptyDashboard({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="panel" data-testid="empty-dashboard">
      <h3 style={{ marginTop: 0, marginBottom: 4 }}>Nothing on this dashboard yet</h3>
      <p className="dash-caption" style={{ marginLeft: 0, marginTop: 0 }}>
        Add a chart by describing it in plain English, or send one from Chat.
      </p>
      <button type="button" className="add-tile add-tile--first" onClick={onAdd}>
        <IconPlus size={20} /> Add your first chart
      </button>
    </div>
  )
}

/** 'Data updated 16 Oct, 08:10', with each cube's time in a tooltip when there are several. */
function DataUpdated({ results, cubeLabel }: { results: DashboardResults | undefined; cubeLabel: (c: string) => string }) {
  const asOf = results?.data_as_of
  if (!asOf?.text) return null
  const text = /^data updated/i.test(asOf.text) ? asOf.text : `Data updated ${asOf.text}`
  const perCube = Object.entries(asOf.per_cube ?? {})
  const caption = <span className="dash-caption" data-testid="data-updated">{text}</span>
  if (perCube.length < 2) return caption
  return (
    <Tooltip label={<>{perCube.map(([cube, t]) => <div key={cube}>{cubeLabel(cube)}: {t}</div>)}</>}>
      {caption}
    </Tooltip>
  )
}

function MissingDashboard({ error }: { error: unknown }) {
  const gone = error instanceof ApiError && error.status === 404
  return (
    <div className="app-page" data-testid="DashboardPage">
      {gone ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>This dashboard was deleted.</h3>
          <Link to="/">Open the first dashboard</Link>
        </div>
      ) : (
        <ErrorNote title="The dashboard could not be loaded" message={errorText(error)} details={errorDetails(error)} />
      )}
    </div>
  )
}


