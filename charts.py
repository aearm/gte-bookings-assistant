"""Turns Claude's chart choice into a Plotly figure."""
import pandas as pd
import plotly.express as px


def build_figure(df: pd.DataFrame, spec: dict):
    """Return a Plotly figure, or None if a table is the better display."""
    chart = spec.get("chart_type", "table")
    x = spec.get("x")
    ys = [y for y in (spec.get("y") or []) if y in df.columns and pd.api.types.is_numeric_dtype(df[y])]
    color = spec.get("color") if spec.get("color") in df.columns else None
    title = spec.get("title", "")

    if chart == "table" or df.empty or x not in df.columns or not ys:
        return None

    y_arg = ys[0] if (len(ys) == 1 or color) else ys  # several measures -> one series each
    if chart == "pie":
        fig = px.pie(df, names=x, values=ys[0], title=title, hole=0.4)
    elif chart == "scatter":
        fig = px.scatter(df, x=x, y=ys[0], color=color, title=title)
    elif chart == "line":
        fig = px.line(df, x=x, y=y_arg, color=color, title=title, markers=len(df) <= 40)
    elif chart == "area":
        fig = px.area(df, x=x, y=y_arg, color=color, title=title)
    elif chart == "horizontal_bar":
        plot_df = df.sort_values(ys[0]) if not color else df
        fig = px.bar(plot_df, x=y_arg, y=x, color=color, orientation="h", title=title,
                     barmode="group")
    else:
        fig = px.bar(df, x=x, y=y_arg, color=color, title=title, barmode="group")

    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10), legend_title_text="",
                      hovermode="x unified" if chart in ("line", "area", "bar") else "closest")
    return fig
