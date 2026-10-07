"""Turns Claude's chart choice into a Plotly figure, in one consistent style."""
import pandas as pd
import plotly.express as px

# Categorical colours in a fixed order (checked for colour-blind safety); dark mode uses the
# same hues stepped for a dark background.
PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
CHART_TYPES = ["bar", "horizontal_bar", "line", "area", "pie", "scatter", "table"]


def build_figure(df: pd.DataFrame, spec: dict, dark: bool = False, height: int | None = None,
                 show_title: bool = True):
    """Return a Plotly figure, or None if a table is the better display."""
    chart = spec.get("chart_type", "table")
    x = spec.get("x")
    ys = [y for y in (spec.get("y") or []) if y in df.columns and pd.api.types.is_numeric_dtype(df[y])]
    color = spec.get("color") if spec.get("color") in df.columns else None
    title = spec.get("title", "") if show_title else ""
    colors = PALETTE["dark" if dark else "light"]

    if chart == "table" or df.empty or x not in df.columns or not ys:
        return None

    y_arg = ys[0] if (len(ys) == 1 or color) else ys  # several measures -> one series each
    common = dict(title=title, color_discrete_sequence=colors)
    if chart == "pie":
        fig = px.pie(df, names=x, values=ys[0], hole=0.45, **common)
        fig.update_traces(sort=False, marker_line_width=2,
                          marker_line_color="#1a1a19" if dark else "#fcfcfb")
    elif chart == "scatter":
        fig = px.scatter(df, x=x, y=ys[0], color=color, **common)
        fig.update_traces(marker_size=9)
    elif chart == "line":
        fig = px.line(df, x=x, y=y_arg, color=color, markers=len(df) <= 40, **common)
        fig.update_traces(line_width=2, marker_size=8)
    elif chart == "area":
        fig = px.area(df, x=x, y=y_arg, color=color, **common)
        fig.update_traces(line_width=2)
    elif chart == "horizontal_bar":
        plot_df = df.sort_values(ys[0]) if not color else df
        fig = px.bar(plot_df, x=y_arg, y=x, color=color, orientation="h", barmode="group", **common)
    else:
        fig = px.bar(df, x=x, y=y_arg, color=color, barmode="group", **common)

    if chart in ("bar", "horizontal_bar"):
        fig.update_layout(barcornerradius=4, bargap=0.3, bargroupgap=0.08)
    if isinstance(y_arg, list):  # several measures: the legend names them, so no "value" axis title
        fig.update_layout(**{"xaxis_title" if chart == "horizontal_bar" else "yaxis_title": ""})
    fig.update_layout(margin=dict(l=10, r=10, t=50 if title else 10, b=10), legend_title_text="",
                      hovermode="x unified" if chart in ("line", "area", "bar") else "closest")
    if height:
        fig.update_layout(height=height)
    return fig
