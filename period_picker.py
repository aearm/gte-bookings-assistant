"""The dashboards' period button. It shows the period ("This year · 1 Jan – 13 Oct 2026 · W1–42")
and opens a calendar: quick choices as rows on the left, two months with ISO week numbers on the
right. Click a day, then another, for a range; click a week number for that week (shift-click
another week number to extend); click a month's name for the whole month; or jump to a year and
week numbers at the bottom. Apply closes it, and every chart follows the new period.
The calendar is a small Streamlit component (HTML, CSS and JavaScript below, no build step)."""
from datetime import date

import streamlit as st

import periods
from inline_component import InlineComponent

STATE_KEY = "dash_period"          # {"preset": name} or {"start": iso, "end": iso (exclusive)}
POPOVER_KEY = "dash_period_popover"
PICKER_KEY = "dash_period_picker"

CSS = r"""
:host { display: block; }
.pp { font: inherit; font-size: 13px; color: var(--st-text-color, #1d1d1f); display: flex; gap: 18px;
      width: min(780px, calc(100vw - 64px)); user-select: none; }
.pp.one { width: min(520px, calc(100vw - 64px)); }
.pp-presets { display: flex; flex-direction: column; min-width: 150px; padding-right: 14px;
              border-right: 1px solid var(--st-border-color, rgba(128,128,128,.25)); }
.pp-presets button { all: unset; cursor: pointer; padding: 6px 10px 6px 28px; border-radius: 8px; position: relative;
                     white-space: nowrap; }
.pp-presets button:hover { background: color-mix(in srgb, var(--st-text-color, #000) 6%, transparent); }
.pp-presets button.on { font-weight: 600; }
.pp-presets button.on::before { content: "✓"; position: absolute; left: 9px; font-weight: 700;
                                color: var(--st-primary-color, #0071e3); }
.pp-main { flex: 1; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.pp-months { display: flex; gap: 22px; flex-wrap: wrap; }
.pp-month { flex: 1; min-width: 250px; }
.pp-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.pp-head .title { all: unset; cursor: pointer; font-weight: 600; font-size: 14px; padding: 4px 8px; border-radius: 8px; }
.pp-head .title:hover { background: color-mix(in srgb, var(--st-primary-color, #0071e3) 10%, transparent); }
.pp-nav { all: unset; cursor: pointer; width: 28px; height: 28px; display: grid; place-items: center;
          border-radius: 50%; font-size: 16px; }
.pp-nav:hover { background: color-mix(in srgb, var(--st-text-color, #000) 7%, transparent); }
.pp-nav.hidden { visibility: hidden; }
.pp-grid { display: grid; grid-template-columns: 34px repeat(7, 1fr); row-gap: 2px; }
.pp-grid .dow, .pp-grid .wkh { font-size: 11px; color: color-mix(in srgb, var(--st-text-color, #000) 50%, transparent);
                               text-align: center; padding: 4px 0; }
.pp-grid .wk { all: unset; cursor: pointer; font-size: 11px; text-align: center; border-radius: 8px; line-height: 30px;
               color: color-mix(in srgb, var(--st-text-color, #000) 55%, transparent); font-variant-numeric: tabular-nums; }
.pp-grid .wk:hover { background: color-mix(in srgb, var(--st-primary-color, #0071e3) 14%, transparent);
                     color: var(--st-primary-color, #0071e3); font-weight: 600; }
.pp-grid .d { all: unset; cursor: pointer; text-align: center; line-height: 30px; height: 30px;
              font-variant-numeric: tabular-nums; position: relative; }
.pp-grid .d.out { color: color-mix(in srgb, var(--st-text-color, #000) 28%, transparent); }
.pp-grid .d.in { background: color-mix(in srgb, var(--st-primary-color, #0071e3) 13%, transparent); }
.pp-grid .d.first { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
.pp-grid .d.last { border-top-right-radius: 8px; border-bottom-right-radius: 8px; }
.pp-grid .d.edge { background: var(--st-primary-color, #0071e3); color: #fff; font-weight: 600; border-radius: 8px; }
.pp-grid .d:not(.edge):hover { box-shadow: inset 0 0 0 1.5px var(--st-primary-color, #0071e3); border-radius: 8px; }
.pp-grid .d.today:not(.edge)::after { content: ""; position: absolute; left: 50%; bottom: 3px; width: 4px; height: 4px;
                                      margin-left: -2px; border-radius: 50%; background: var(--st-primary-color, #0071e3); }
.pp-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
           border-top: 1px solid var(--st-border-color, rgba(128,128,128,.25)); padding-top: 10px; }
.pp-weeks { display: flex; align-items: center; gap: 6px; color: color-mix(in srgb, var(--st-text-color, #000) 65%, transparent); }
.pp-weeks select, .pp-weeks input { font: inherit; font-size: 13px; color: var(--st-text-color, #1d1d1f);
       background: var(--st-secondary-background-color, #fff); border: 1px solid var(--st-border-color, rgba(128,128,128,.35));
       border-radius: 8px; padding: 3px 6px; }
.pp-weeks input { width: 46px; }
.pp-summary { font-weight: 600; }
.pp-summary span { font-weight: 400; color: color-mix(in srgb, var(--st-text-color, #000) 55%, transparent); }
.pp-actions { display: flex; gap: 8px; }
.pp-btn { all: unset; cursor: pointer; padding: 6px 14px; border-radius: 980px; font-weight: 500;
          border: 1px solid var(--st-border-color, rgba(128,128,128,.35)); }
.pp-btn.primary { background: var(--st-primary-color, #0071e3); color: #fff; border-color: transparent; }
.pp-btn:hover { filter: brightness(1.05); }
.pp-hint { font-size: 11.5px; color: color-mix(in srgb, var(--st-text-color, #000) 50%, transparent); }
@media (max-width: 640px) { .pp { flex-direction: column; } .pp-presets { flex-direction: row; flex-wrap: wrap;
  border-right: none; padding-right: 0; } }
"""

JS = r"""
const DAY = 86400000;
const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const num = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / DAY; };
const iso = (n) => new Date(n * DAY).toISOString().slice(0, 10);
const ymd = (n) => { const d = new Date(n * DAY); return [d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()]; };
const weekday = (n) => (new Date(n * DAY).getUTCDay() + 6) % 7;            // Monday = 0
const monthStart = (y, m) => Date.UTC(y, m, 1) / DAY;
const isoWeek = (n) => {                                                   // ISO 8601 week of a day
  const thursday = n - weekday(n) + 3;
  const year = new Date(thursday * DAY).getUTCFullYear();
  return { year, week: Math.floor((thursday - Date.UTC(year, 0, 1) / DAY) / 7) + 1 };
};
const weekMonday = (year, week) => {                                       // Monday of an ISO week
  const jan4 = Date.UTC(year, 0, 4) / DAY;
  return jan4 - weekday(jan4) + (week - 1) * 7;
};
const weeksIn = (year) => isoWeek(Date.UTC(year, 11, 28) / DAY).week;
const text = (a, b) => {
  const [y1, m1, d1] = ymd(a), [y2, m2, d2] = ymd(b);
  if (a === b) return `${d1} ${SHORT[m1]} ${y1}`;
  return `${d1} ${SHORT[m1]}${y1 === y2 ? "" : " " + y1} – ${d2} ${SHORT[m2]} ${y2}`;
};
const weeksText = (a, b) => {
  const w1 = isoWeek(a), w2 = isoWeek(b);
  if (w1.year === w2.year && w1.week === w2.week) return `week ${w1.week}`;
  if (w1.year === w2.year) return `weeks ${w1.week}–${w2.week}`;
  return `weeks ${w1.week} (${w1.year}) – ${w2.week} (${w2.year})`;
};
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  let root = parentElement.querySelector(".pp");
  if (!root) { root = el("div", "pp"); parentElement.appendChild(root); }
  const S = root._s || (root._s = {});
  const key = `${data.start}|${data.end}|${data.preset}`;
  if (S.key !== key) {                       // a new period from Python: show it
    S.key = key; S.a = num(data.start); S.b = num(data.end) - 1; S.anchor = null; S.hover = null; S.lastWeek = null;
    const [y, m] = ymd(S.b);
    S.view = m === 0 ? [y - 1, 11] : [y, m - 1]; // the end month on the right
  }
  const today = num(data.today);
  const send = (a, b, preset) => setStateValue("selection", { start: iso(a), end: iso(b + 1), preset: preset || "", nonce: Date.now() });

  function range() {
    if (S.anchor !== null && S.hover !== null) return [Math.min(S.anchor, S.hover), Math.max(S.anchor, S.hover)];
    return [S.a, S.b];
  }

  function month(y, m, showPrev, showNext) {
    const box = el("div", "pp-month");
    const head = el("div", "pp-head");
    const prev = el("button", "pp-nav" + (showPrev ? "" : " hidden"), "‹");
    prev.title = "Earlier month";
    prev.onclick = () => { S.view = S.view[1] === 0 ? [S.view[0] - 1, 11] : [S.view[0], S.view[1] - 1]; render(); };
    const title = el("button", "title", `${MONTHS[m]} ${y}`);
    title.title = "Pick the whole month";
    title.onclick = () => { S.a = monthStart(y, m); S.b = monthStart(m === 11 ? y + 1 : y, (m + 1) % 12) - 1; S.anchor = null; S.preset = ""; render(); };
    const next = el("button", "pp-nav" + (showNext ? "" : " hidden"), "›");
    next.title = "Later month";
    next.onclick = () => { S.view = S.view[1] === 11 ? [S.view[0] + 1, 0] : [S.view[0], S.view[1] + 1]; render(); };
    head.append(prev, title, next);
    box.append(head);

    const grid = el("div", "pp-grid");
    grid.append(el("div", "wkh", "Wk"));
    for (const d of ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]) grid.append(el("div", "dow", d));
    const first = monthStart(y, m), last = monthStart(m === 11 ? y + 1 : y, (m + 1) % 12) - 1;
    const [a, b] = range();
    for (let mon = first - weekday(first); mon <= last; mon += 7) {
      const w = isoWeek(mon);
      const wk = el("button", "wk", String(w.week));
      wk.title = `Week ${w.week} of ${w.year} — shift-click another week to pick several`;
      wk.onclick = (ev) => {
        if (ev.shiftKey && S.lastWeek !== null) { S.a = Math.min(S.lastWeek, mon); S.b = Math.max(S.lastWeek, mon) + 6; }
        else { S.a = mon; S.b = mon + 6; S.lastWeek = mon; }
        S.anchor = null; S.preset = ""; render();
      };
      grid.append(wk);
      for (let n = mon; n < mon + 7; n++) {
        const cell = el("button", "d", String(ymd(n)[2]));
        const cls = [];
        if (n < first || n > last) cls.push("out");
        if (n >= a && n <= b) cls.push(n === a || n === b ? "edge" : "in");
        if (n === a || weekday(n) === 0) cls.push("first");
        if (n === b || weekday(n) === 6) cls.push("last");
        if (n === today) cls.push("today");
        cell.className = "d " + cls.join(" ");
        cell.onclick = () => {
          if (S.anchor === null) { S.anchor = n; S.hover = n; S.a = n; S.b = n; }
          else { S.a = Math.min(S.anchor, n); S.b = Math.max(S.anchor, n); S.anchor = null; S.hover = null; }
          S.preset = ""; render();
        };
        cell.onmouseenter = () => { if (S.anchor !== null && S.hover !== n) { S.hover = n; render(); } };
        grid.append(cell);
      }
    }
    box.append(grid);
    return box;
  }

  function render() {
    root.replaceChildren();
    const presets = el("div", "pp-presets");
    for (const p of data.presets) {
      const b = el("button", p.name === data.preset && S.key === key && S.preset !== "" ? "on" : "", p.name);
      b.title = text(num(p.start), num(p.end) - 1);
      b.onclick = () => send(num(p.start), num(p.end) - 1, p.name);
      presets.append(b);
    }
    const main = el("div", "pp-main");
    const months = el("div", "pp-months");
    const [y, m] = S.view, [y2, m2] = m === 11 ? [y + 1, 0] : [y, m + 1];
    const two = window.innerWidth >= 1000;          // two months side by side on a wide window
    root.classList.toggle("one", !two);
    months.append(month(y, m, true, !two));
    if (two) months.append(month(y2, m2, false, true));
    main.append(months);

    const foot = el("div", "pp-foot");
    const weeks = el("div", "pp-weeks");
    const [a, b] = range();
    const wa = isoWeek(a), wb = isoWeek(b);
    const yearSel = el("select");
    const thisYear = isoWeek(today).year;
    for (let yr = thisYear + 1; yr >= data.first_year; yr--) {
      const o = el("option", "", String(yr)); o.value = yr; if (yr === wb.year) o.selected = true; yearSel.append(o);
    }
    const from = el("input"); from.type = "number"; from.min = 1; from.max = 53; from.value = wa.year === wb.year ? wa.week : 1;
    const to = el("input"); to.type = "number"; to.min = 1; to.max = 53; to.value = wb.week;
    const go = el("button", "pp-btn", "Show");
    go.onclick = () => {
      const yr = Number(yearSel.value), top = weeksIn(yr);
      let w1 = Math.min(Math.max(1, Number(from.value) || 1), top), w2 = Math.min(Math.max(1, Number(to.value) || w1), top);
      if (w2 < w1) [w1, w2] = [w2, w1];
      S.a = weekMonday(yr, w1); S.b = weekMonday(yr, w2) + 6; S.anchor = null; S.preset = "";
      const [vy, vm] = ymd(S.b); S.view = vm === 0 ? [vy - 1, 11] : [vy, vm - 1]; render();
    };
    weeks.append(el("span", "", "Year"), yearSel, el("span", "", "weeks"), from, el("span", "", "to"), to, go);

    const right = el("div", "pp-actions");
    const summary = el("div", "pp-summary", text(a, b) + " ");
    summary.append(el("span", "", `· ${b - a + 1} day${b === a ? "" : "s"} · ${weeksText(a, b)}`));
    const cancel = el("button", "pp-btn", "Reset");
    cancel.onclick = () => { S.a = num(data.start); S.b = num(data.end) - 1; S.anchor = null; S.hover = null; delete S.preset; render(); };
    const apply = el("button", "pp-btn primary", "Apply");
    apply.onclick = () => send(S.a, S.b, "");
    right.append(cancel, apply);
    foot.append(summary, right);
    const hint = el("div", "pp-hint", S.anchor !== null ? "Now click the last day." :
      "Click a day and then another for a range · a week number for that week (shift-click to add weeks) · a month's name for the month.");
    main.append(foot, weeks, hint);
    root.append(presets, main);
  }
  render();
}
"""

_calendar = InlineComponent("period_calendar", css=CSS, js=JS)


def current() -> tuple[date, date, str]:
    """(start, end exclusive, preset) of the period picked on the dashboards. A preset ("This
    month") always means that period as of today."""
    picked = st.session_state.get(STATE_KEY) or {}
    if picked.get("preset") in periods.PRESETS:
        start, end = periods.preset_range(picked["preset"])
        return start, end, picked["preset"]
    try:
        return date.fromisoformat(picked["start"]), date.fromisoformat(picked["end"]), ""
    except (KeyError, TypeError, ValueError):
        start, end = periods.preset_range(periods.DEFAULT_PRESET)
        return start, end, periods.DEFAULT_PRESET


def choose(selection: dict) -> None:
    """Keep a period chosen on the calendar ({"start", "end" exclusive, "preset"})."""
    if selection.get("preset") in periods.PRESETS:
        st.session_state[STATE_KEY] = {"preset": selection["preset"]}
        return
    start, end = date.fromisoformat(selection["start"]), date.fromisoformat(selection["end"])
    if end <= start:
        raise ValueError("The period ends before it starts.")
    st.session_state[STATE_KEY] = {"start": start.isoformat(), "end": end.isoformat()}


def _on_pick() -> None:
    value = st.session_state.get(PICKER_KEY)
    selection = value.get("selection") if hasattr(value, "get") else getattr(value, "selection", None)
    if selection:
        try:
            choose(selection)
        except (KeyError, TypeError, ValueError):
            return
        st.session_state[POPOVER_KEY] = False  # close the calendar


def picker() -> tuple[date, date, bool]:
    """The period button (with its calendar). Returns (start, end exclusive, weekly)."""
    start, end, preset = current()
    pop = st.popover(periods.label(start, end, preset), icon=":material/calendar_month:", key=POPOVER_KEY,
                     on_change="rerun", help="Pick the period: a quick choice, days or weeks on the calendar")
    with pop:
        if pop.open:
            _calendar(key=PICKER_KEY, on_selection_change=_on_pick, data={
                "start": start.isoformat(), "end": end.isoformat(), "preset": preset,
                "today": date.today().isoformat(), "first_year": date.today().year - 10,
                "presets": [{"name": n, "start": s.isoformat(), "end": e.isoformat()}
                            for n in periods.PRESETS for s, e in [periods.preset_range(n)]]})
    return start, end, periods.is_weekly(start, end, preset)
