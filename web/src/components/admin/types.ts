// Shapes of the admin endpoints of docs/api.md (cubes, cube setup, glossary, settings, updates, usage).
// The common ones (Decision, Job) live in api/types.ts. Fields marked optional are read defensively:
// the contract names them but doesn't spell out every field.

// ---------------------------------------------------------------- cubes & data layer --

export type CubeInfo = {
  name: string
  label: string
  ready: boolean        // its structure and values have been read
  setup: string         // cube_setup.status_label: "Ready", "2 steps waiting", "Not set up" ...
  usable: boolean       // false: the meaning layer says the cube has no data
  coverage: string      // e.g. "1 Jan 2024 to 15 Oct 2026"
  in_layer?: boolean    // (server extra) in the data layer
}

/** data_layer.status() */
export type LayerStatus = {
  built: string         // ISO time, "" when never built
  model: string
  cubes: string[]       // connected cubes that are in the layer
  missing: string[]     // connected cubes not in the layer yet
  changed: string[]     // cubes whose structure changed since the layer was built
  entities: number      // shared dimensions
  ready: boolean
}

export type CubesData = {
  server_cubes: string[]
  enabled: string[]
  cubes: CubeInfo[]
  layer: LayerStatus
  drift: string[]       // cubes the meaning layer was built for an earlier structure of
  // extras the server sends beyond docs/api.md (all optional here)
  server_cubes_detail?: { name: string; label: string; updated: string }[]
  server_error?: string // the cube server couldn't be asked for its cubes
  local?: boolean       // local mode: the files in data/local, no server
  server?: string       // the server's address
  meaning?: { decisions: number; agreed: number }
  layer_model?: string
}

// ---------------------------------------------------------------- cube setup --

export type SetupOption = { label: string; meaning: string; in_data: string; date_to_use: string }
export type SetupItem = {
  term: string
  kind: string
  clear: boolean
  meaning: string
  in_data: string
  date_to_use: string
  question: string
  options: SetupOption[]
  state: 'question' | 'proposal'
  done: string          // "" while open; "answered", "skipped", "confirmed", "rejected"
}
export type SetupProgress = { structure: boolean; drafted: boolean; questions: number; proposals: number; ready: boolean }
export type SuggestedChart = { title: string; question: string; chart_type: string; width: string }

export type OpenQuestion = { index: number; term: string; question: string; options: SetupOption[] }
export type OpenProposal = { index: number; term: string; meaning: string; in_data: string }

/** GET /cubes/{cube}/setup: the setup's progress and what is still open. The server sends the open
 * `questions` and `proposals` (each with its index); the whole `items` list of cube_setup.load(cube) is
 * read too, if sent. */
export type SetupState = {
  cube?: string
  label?: string
  status?: string
  progress?: SetupProgress
  structure_read?: string   // when the structure was last read, e.g. "16 Oct 14:05"
  drafted?: string
  summary?: string
  questions?: OpenQuestion[]
  proposals?: OpenProposal[]
  items?: SetupItem[]
  suggested_charts?: SuggestedChart[]
  example_questions?: string[]
}

// ---------------------------------------------------------------- glossary --

export const GLOSSARY_COLUMNS = ['Term', 'Meaning', 'Measure', 'Date to use', 'Status', 'Agreed by'] as const
export type GlossaryColumn = (typeof GLOSSARY_COLUMNS)[number]
export type GlossaryRow = Record<GlossaryColumn, string>
export const GLOSSARY_STATUSES = ['Draft', 'Agreed'] as const

export type GlossaryData = { cube: string; label: string; summary: string; rows: GlossaryRow[]; updated: string; drafts?: number }

// ---------------------------------------------------------------- settings & updates --

export type SettingsStatus = {
  api_key: 'set' | 'missing' | 'env'
  api_key_where?: 'saved' | 'env' | 'missing'   // (server extra) "env": read from .env as plain text
  server: { address: string; database: string; login_saved: boolean; username?: string; windows_login?: boolean }
  admin_password_set: boolean
  data_source?: string
  models?: Record<string, unknown>
}

/** updates.last_status(): written by the updater after each update */
export type LastUpdate = { time?: string; ok?: boolean; from?: string; to?: string; error?: string }

export type UpdatesInfo = {
  current: string
  latest: string | null
  published: string
  notes: string
  developer_copy: boolean
  /** updating | up_to_date | available | no_release | check_failed (or, read defensively, the last
   * update's outcome) */
  status: string | LastUpdate | null
  last?: LastUpdate | null   // how the last update went
  error?: string             // the check failed, or the download after Update did
  page?: string
}

export type Health = { ok: boolean; version: string; data_source?: string; up_seconds?: number }

// ---------------------------------------------------------------- usage --

/** One line of data/usage.jsonl (usage.Recorder.summary) */
export type UsageEntry = {
  time: string
  kind: string
  label: string
  seconds: number
  cost: number
  claude_calls: number
  claude_seconds?: number
  stages?: Record<string, number>
  cache_hit?: number
  input_tokens?: number
  output_tokens?: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  memory?: boolean
  outcome?: string
  error?: string
}

/** usage.cost_report() */
export type CostReport = {
  today: number
  week: number
  month: number
  total: number
  since: string | null
  activities: { Activity: string; Times: number; 'From memory': number; 'This month ($)': number; 'Total ($)': number }[]
  models: { Model: string; Calls: number; 'Tokens read': number; 'Tokens written': number; 'Total ($)': number }[]
  daily: { Day: string; 'Cost ($)': number }[]
}

/** recent = the latest questions (up to 300), newest first */
export type UsageData = { report: CostReport; recent: UsageEntry[] }
