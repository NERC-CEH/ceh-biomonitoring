"""cehbio report: a plain summary report per deployment (and one for the whole project), as one
self-contained HTML page each, in the results folder: <results>/<pipeline>/<project>/report/.

It lays out the tables and words from `cehbio report-data` (made first if they aren't there), so the R
report (the cehbio R package) says exactly the same. It describes what was recorded; it doesn't
interpret or compare with other places.
"""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import pandas as pd

# UKCEH house style (the same values as the UKCEH and partner reports, theme_report.R)
STYLE = {"font": "Arial", "ink": "#000000", "ink_2": "#4d4d4d", "grid": "#e3e3e3", "surface": "#ffffff",
         "mint": "#D6EAE6", "neutral": "#bdbdbd", "main": "#133b64",
         "categorical": ["#133b64", "#f4c03d", "#477AE2", "#e76124", "#67ccea", "#7f1518", "#4db264", "#cfbcd5"]}

CSS = """
:root{--ink:%(ink)s;--ink2:%(ink_2)s;--grid:%(grid)s;--mint:%(mint)s;--main:%(main)s}
body{font-family:%(font)s,Helvetica,sans-serif;color:var(--ink);background:#fff;margin:0;line-height:1.5}
header{background:var(--main);color:#fff;padding:28px 16px}
header h1{margin:0 0 4px;font-size:28px}header p{margin:0;opacity:.9}
main{max-width:1000px;margin:0 auto;padding:8px 16px 48px}
h2{border-bottom:2px solid var(--mint);padding-bottom:4px;margin-top:36px}
.note{background:#fff8e1;border-left:4px solid #f4c03d;padding:10px 14px;margin:16px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--mint);padding:12px 14px;border-radius:6px}.tile b{display:block;font-size:26px}
.tile span{color:var(--ink2);font-size:14px}
table{border-collapse:collapse;width:100%%;font-size:14px;margin:8px 0 16px}
th{background:var(--mint);text-align:left;padding:6px 8px}td{padding:5px 8px;border-bottom:1px solid var(--grid)}
td.n,th.n{text-align:right}figure{margin:12px 0 20px}figure img{max-width:100%%}
figcaption{color:var(--ink2);font-size:14px}.small{color:var(--ink2);font-size:13px}
a.button{display:inline-block;background:var(--main);color:#fff;padding:6px 12px;border-radius:4px;text-decoration:none}
details{margin:6px 0 16px}summary{cursor:pointer;color:var(--main)}
""" % STYLE


def _e(x) -> str:
    return html.escape(str(x))


def _fig(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _axes(w=9.5, h=3.2, rows=1, share=True):
    import matplotlib
    matplotlib.use("Agg")
    import logging
    import matplotlib.pyplot as plt
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)   # Arial isn't on every server
    plt.rcParams.update({"font.family": [STYLE["font"], "Liberation Sans", "DejaVu Sans"], "font.size": 10,
                         "axes.edgecolor": STYLE["grid"], "axes.labelcolor": STYLE["ink_2"],
                         "xtick.color": STYLE["ink_2"], "ytick.color": STYLE["ink_2"],
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": STYLE["grid"], "axes.axisbelow": True})
    fig, ax = plt.subplots(rows, 1, figsize=(w, h * rows), sharex=share, squeeze=False)
    return fig, [a[0] for a in ax]


def _months(ax) -> None:
    """Date axes labelled by month (Jun, Jul ...), not crowded dates."""
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=0))


def fig_working(n: pd.DataFrame) -> str:
    """Hours worked each night: the deployment's nights in navy, nights outside it (set-up tests) in grey."""
    fig, (ax,) = _axes(h=2.4)
    d = pd.to_datetime(n["night"])
    inside = n["in_deployment"].astype(bool) if "in_deployment" in n else pd.Series(True, index=n.index)
    ax.bar(d[inside], n.loc[inside, "hours_worked"], width=0.8, color=STYLE["main"], label="during the deployment")
    if (~inside).any():
        ax.bar(d[~inside], n.loc[~inside, "hours_worked"], width=0.8, color=STYLE["neutral"],
               label="outside it (e.g. set-up tests)")
        ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, fontsize=9)
    ax.set_ylabel("hours working")
    ax.grid(axis="x", visible=False)
    _months(ax)
    return _fig(fig)


def fig_activity(n: pd.DataFrame, unit: str) -> str:
    """Activity per night, with the night's temperature in its own panel below (never two scales on one)."""
    n = n[n["in_deployment"].astype(bool)] if "in_deployment" in n else n
    has_t = "temperature_mean_c" in n and n["temperature_mean_c"].notna().any()
    fig, axes = _axes(h=2.6, rows=2 if has_t else 1)
    d = pd.to_datetime(n["night"])
    axes[0].bar(d, n["individuals_per_hour"].fillna(0), width=0.8, color=STYLE["main"])
    axes[0].set_ylabel(f"{unit}\nper hour")
    axes[0].grid(axis="x", visible=False)
    if has_t:
        axes[1].plot(d, n["temperature_mean_c"], color=STYLE["categorical"][3], lw=2, marker="o", ms=3)
        axes[1].set_ylabel("mean temperature\nwhile working (°C)")
    _months(axes[-1])
    return _fig(fig)


def fig_bars(labels, values, xlabel: str) -> str:
    """Horizontal bars, largest at the top, one colour (it's magnitude, not identity), values labelled."""
    fig, (ax,) = _axes(h=max(1.6, 0.32 * len(labels) + 0.6), share=False)
    y = range(len(labels))[::-1]
    ax.barh(list(y), values, color=STYLE["main"], height=0.7)
    ax.set_yticks(list(y), labels)
    for yy, v in zip(y, values):
        ax.text(v, yy, f" {int(v):,}", va="center", fontsize=9, color=STYLE["ink_2"])
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    return _fig(fig)


def fig_temperature(n: pd.DataFrame, unit: str) -> str | None:
    n = n[n["in_deployment"].astype(bool)] if "in_deployment" in n else n
    if "temperature_mean_c" not in n or n["temperature_mean_c"].notna().sum() < 5:
        return None
    fig, (ax,) = _axes(w=5.5, h=3.6, share=False)
    ax.scatter(n["temperature_mean_c"], n["individuals_per_hour"], s=40, color=STYLE["main"],
               edgecolor="white", linewidth=1.5)
    ax.set_xlabel("mean temperature while working (°C)")
    ax.set_ylabel(f"{unit} per hour")
    return _fig(fig)


def _table(df: pd.DataFrame, numeric=()) -> str:
    head = "".join(f"<th class='{'n' if c in numeric else ''}'>{_e(c)}</th>" for c in df.columns)
    rows = "".join("<tr>" + "".join(f"<td class='{'n' if c in numeric else ''}'>{_e(v)}</td>" for c, v in r.items())
                   + "</tr>" for r in df.to_dict("records"))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


def _download(df: pd.DataFrame, name: str, label: str) -> str:
    b = base64.b64encode(df.to_csv(index=False).encode("utf-8")).decode()
    return f"<a class='button' download='{_e(name)}' href='data:text/csv;base64,{b}'>{_e(label)}</a>"


def _name(r) -> str:
    cn = r.get("common_name")
    return f"{cn} ({r['taxon']})" if isinstance(cn, str) and cn.strip() else str(r["taxon"])


def _species_section(sp: pd.DataFrame, pipe: str, labels: dict, dep: str) -> str:
    out = []
    if sp.empty:
        return "<p>Nothing was recorded.</p>"
    if pipe == "images":
        groups = sp.assign(group=sp["kind"].where(sp["kind"] == "other insect", "Moths"))
        groups.loc[groups["kind"] == "other insect", "group"] = groups["taxon"]
        g = groups.groupby("group")["individuals"].sum().sort_values(ascending=False)
        top = g.head(9)
        if len(g) > 9:
            top = pd.concat([top.head(8), pd.Series({"all other groups": g.iloc[8:].sum()})])
        out.append("<h3>Insect groups</h3>")
        out.append(f"<figure><img alt='individual insects per group' src='{fig_bars(list(top.index), list(top.values), 'individual insects')}'>"
                   "<figcaption>Individual insects in each group. Moths are counted together; other insects by "
                   "the insect order the model gave.</figcaption></figure>")
        sp = sp[sp["kind"] == "moth"]
        title = "Moth species"
    else:
        title = "Species"
    if sp.empty:
        return "\n".join(out)
    top = sp.sort_values("individuals", ascending=False).head(20)
    names = [_name(r) for r in top.to_dict("records")]
    out.append(f"<h3>{title}: the 20 most often recorded</h3>")
    out.append(f"<figure><img alt='{_e(title)}' src='{fig_bars(names, list(top['individuals']), labels['unit'])}'></figure>")
    tab = pd.DataFrame({"species": names, labels["unit"]: top["individuals"].map("{:,}".format),
                        "nights": top["nights"], "first": top["first_night"], "last": top["last_night"],
                        "mean score": top["score_mean"].map(lambda v: f"{v:.2f}" if pd.notna(v) else "")})
    out.append(_table(tab, numeric=(labels["unit"], "nights", "mean score")))
    full = sp.sort_values("individuals", ascending=False)
    keep = [c for c in ("taxon", "common_name", "individuals", "nights", "first_night", "last_night", "score_mean",
                        "score_max", "unlikely_this_month") if c in full.columns]
    out.append(f"<p>{len(full):,} {title.lower()} in all. " +
               _download(full[keep], f"{dep}_species.csv", "Download the full list (CSV)") + "</p>")
    return "\n".join(out)


def _methods(t: dict) -> str:
    m = t["methods"]
    parts = [f"<p>{_e(m['how'])}</p>", f"<p>{_e(m['unit'])}</p>" if m.get("unit") else "",
             f"<p>{_e(m['night'])}</p>", f"<p>{_e(m['weather'])} {_e(m['moon'])}</p>"]
    if m.get("models"):
        parts.append("<p>Models used:</p><ul>" + "".join(f"<li>{_e(x)}</li>" for x in m["models"]) + "</ul>")
    if m.get("citations"):
        parts.append("<p>Please cite:</p><ul>" + "".join(f"<li>{_e(x)}</li>" for x in m["citations"]) + "</ul>")
    if m.get("notes"):
        parts.append("<details><summary>Notes on how this report was made</summary><ul>"
                     + "".join(f"<li>{_e(x)}</li>" for x in m["notes"]) + "</ul></details>")
    parts.append(f"<p class='small'>{_e(m['made_with'])}</p>")
    return "\n".join(parts)


def _page(title: str, subtitle: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{_e(title)}</title>"
            f"<style>{CSS}</style></head><body><header><h1>{_e(title)}</h1><p>{_e(subtitle)}</p></header>"
            f"<main>{body}</main></body></html>")


def deployment_page(data: Path, dep: str, t: dict) -> str:
    pipe, lab = t["pipeline"], t["labels"]
    deps = pd.read_parquet(data / "deployments.parquet")
    d = deps[deps["deployment_id"] == dep].iloc[0]
    n = pd.read_parquet(data / "nights.parquet")
    n = n[n["deployment_id"] == dep].sort_values("night")
    sp = pd.read_parquet(data / "species.parquet")
    sp = sp[sp["deployment_id"] == dep] if len(sp) else sp
    inside = n[n["in_deployment"].astype(bool)] if "in_deployment" in n else n
    main_sp = sp[sp["kind"] != "other insect"] if pipe == "images" and len(sp) else sp
    tiles = [(f"{int(d.nights_worked):,}", "nights working"), (f"{round(d.hours_worked):,}", "hours working"),
             (f"{int(d.individuals):,}", lab["unit"]),
             (f"{len(main_sp):,}", "moth species" if pipe == "images" else "species")]
    body = [f"<div class='note'>{_e(t['methods']['caveat'])}</div>",
            "<h2>Summary</h2><div class='tiles'>" + "".join(f"<div class='tile'><b>{v}</b><span>{_e(k)}</span></div>"
                                                            for v, k in tiles) + "</div>",
            "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in t["deployments"].get(dep, [])) + "</ul>",
            "<h2>When it was working</h2>",
            f"<figure><img alt='hours working each night' src='{fig_working(n)}'><figcaption>Hours between the first "
            f"and last {lab['file']} of each night.</figcaption></figure>",
            f"<h2>Activity</h2><figure><img alt='activity per night' src='{fig_activity(n, lab['unit'])}'>"
            f"<figcaption>{_e(lab['unit'].capitalize())} per hour the device was working, each night"
            + (", with the night's mean temperature below." if "temperature_mean_c" in n else ".") + "</figcaption></figure>"]
    ft = fig_temperature(n, lab["unit"])
    if ft:
        body.append(f"<figure><img alt='activity and temperature' src='{ft}' style='max-width:520px'>"
                    f"<figcaption>Each dot is a night.</figcaption></figure>")
    cols = [c for c in ("night", "hours_worked", "files", "individuals", "individuals_per_hour", "temperature_mean_c",
                        "precipitation_total_mm", "wind_speed_mean_ms", "moon_illumination") if c in inside.columns]
    body.append("<details><summary>Night by night (table)</summary>" + _table(inside[cols].round(2), numeric=cols[1:])
                + _download(inside, f"{dep}_nights.csv", "Download (CSV)") + "</details>")
    body.append(f"<h2>What was recorded</h2>{_species_section(sp, pipe, lab, dep)}")
    body.append(f"<h2>How this was done</h2>{_methods(t)}")
    when = f"{d.first_night} to {d.last_night}" if d.first_night else ""
    return _page(f"{dep}", f"{lab['what'].capitalize()} · {t['project']} · {when}", "\n".join(body))


def project_page(data: Path, t: dict) -> str:
    lab = t["labels"]
    deps = pd.read_parquet(data / "deployments.parquet").sort_values("deployment_id")
    tab = pd.DataFrame({"deployment": deps["deployment_id"], "first night": deps["first_night"],
                        "last night": deps["last_night"], "nights": deps["nights_worked"],
                        "hours": deps["hours_worked"].round(0).astype(int), lab["unit"]: deps["individuals"].map("{:,}".format),
                        "species / groups": deps["taxa"]})
    per_hour = (deps["individuals"] / deps["hours_worked"].where(deps["hours_worked"] > 0)).fillna(0)
    body = [f"<div class='note'>{_e(t['methods']['caveat'])}</div>",
            "<h2>Summary</h2><ul>" + "".join(f"<li>{_e(x)}</li>" for x in t["project_summary"]) + "</ul>",
            "<h2>Deployments</h2>", _table(tab, numeric=("nights", "hours", lab["unit"], "species / groups")),
            f"<figure><img alt='activity per deployment' src='{fig_bars(list(deps['deployment_id']), list(per_hour.round(1)), lab['unit'] + ' per hour working')}'>"
            "<figcaption>Average activity per hour working. Deployments ran on different nights and places, so "
            "this describes them; it doesn't rank them.</figcaption></figure>",
            "<p>" + " · ".join(f"<a href='{_e(x)}.html'>{_e(x)}</a>" for x in deps["deployment_id"]) + "</p>",
            f"<h2>How this was done</h2>{_methods(t)}"]
    return _page(f"{t['project']}", f"{lab['what'].capitalize()} · {len(deps)} deployments", "\n".join(body))


def make(settings, pipeline: str, project: str, sites: str | None = None, weather: str = "open-meteo",
         refresh: bool = False) -> list[Path]:
    from . import data as D
    data = settings.outputs_root / pipeline / project / "report" / "data"
    if refresh or not (data / "text.json").exists():
        D.build(settings, pipeline, project, sites=sites, weather=weather)
    t = json.loads((data / "text.json").read_text(encoding="utf-8"))
    out = data.parent
    written = []
    for dep in t["deployments"]:
        p = out / f"{dep}.html"
        p.write_text(deployment_page(data, dep, t), encoding="utf-8")
        written.append(p)
    if len(t["deployments"]) > 1:
        p = out / f"{project}_project.html"
        p.write_text(project_page(data, t), encoding="utf-8")
        written.append(p)
    return written


def add_command(sub, common) -> None:
    import argparse
    p = sub.add_parser("report", parents=[common], help="a summary report per deployment and for the project (HTML)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pipeline", choices=["birds", "bats", "images"])
    p.add_argument("--project", required=True)
    p.add_argument("--sites", help="CSV: deployment, latitude, longitude, timezone, clock, start, end")
    p.add_argument("--weather", default="open-meteo", choices=["open-meteo", "era5-land", "none"])
    p.add_argument("--refresh", action="store_true", help="remake the report data first (after new results)")

    def go(a):
        from ..settings import Settings
        s = Settings.load(getattr(a, "profile", None))
        files = make(s, a.pipeline, a.project, a.sites, a.weather, a.refresh or bool(a.sites))
        print(f"{len(files)} reports in {files[0].parent}:" if files else "No reports made.")
        for f in files:
            print(f"  {f.name}")
    p.set_defaults(func=go)
