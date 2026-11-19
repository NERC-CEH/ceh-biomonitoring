"""Word and PDF versions of the summary reports, with Quarto (https://quarto.org).

The same sections, words and charts as the HTML report (html.py), written as Markdown with the charts as
image files, then turned into Word (.docx) or PDF by Quarto. PDF uses Quarto's own engine (Typst), so
LaTeX isn't needed. Quarto comes with the toolkit's reports extra (pip install quarto-cli), or use one you
have installed.

A Word template can be given (--reference-doc): its styles (fonts, headings, colours) are used. The
in-house plug-in uses this for the UKCEH report template.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from . import html as H

FORMATS = {"html": None, "docx": "docx", "pdf": "typst"}


def quarto() -> str:
    q = shutil.which("quarto")
    if q:
        return q
    try:                                    # the quarto-cli package's own copy
        import quarto_cli  # noqa: F401
        for cand in (Path(quarto_cli.__file__).parent / "bin" / n for n in ("quarto", "quarto.exe", "quarto.cmd")):
            if cand.exists():
                return str(cand)
    except ImportError:
        pass
    raise SystemExit("Word and PDF reports need Quarto: pip install quarto-cli (or ./install.sh reports), "
                     "or install it from https://quarto.org. HTML reports don't need it.")


def _png(uri: str, path: Path) -> str:
    path.write_bytes(base64.b64decode(uri.split(",", 1)[1]))
    return path.name


def _md_table(df: pd.DataFrame, right=()) -> str:
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    rule = "|" + "|".join("---:" if c in right else ":---" for c in cols) + "|"
    rows = ["| " + " | ".join(str(v).replace("|", "/") for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, rule, *rows])


def _methods(t: dict) -> list[str]:
    m = t["methods"]
    out = [m["how"], "", m.get("unit", ""), "", m["night"], "", f"{m['weather']} {m['moon']}", ""]
    if m.get("models"):
        out += ["Models used:", ""] + [f"- {x}" for x in m["models"]] + [""]
    if m.get("citations"):
        out += ["Please cite:", ""] + [f"- {x}" for x in m["citations"]] + [""]
    if m.get("notes"):
        out += ["Notes on how this report was made:", ""] + [f"- {x}" for x in m["notes"]] + [""]
    out.append(f"*{m['made_with']}*")
    return out


def deployment_md(data: Path, dep: str, t: dict, figs: Path) -> str:
    pipe, lab = t["pipeline"], t["labels"]
    d = pd.read_parquet(data / "deployments.parquet").set_index("deployment_id").loc[dep]
    n = pd.read_parquet(data / "nights.parquet")
    n = n[n["deployment_id"] == dep].sort_values("night")
    inside = n[n["in_deployment"].astype(bool)] if "in_deployment" in n else n
    sp = pd.read_parquet(data / "species.parquet")
    sp = sp[sp["deployment_id"] == dep] if len(sp) else sp
    main = sp[sp["kind"] != "other insect"] if pipe == "images" and len(sp) else sp
    sp_word = "moth species" if pipe == "images" else "species"
    L = [f"> {t['methods']['caveat']}", "", "# Summary", "",
         _md_table(pd.DataFrame([{"nights working": f"{int(d.nights_worked):,}", "hours working": f"{round(d.hours_worked):,}",
                                  lab["unit"]: f"{int(d.individuals):,}", sp_word: f"{len(main):,}"}]),
                   right=("nights working", "hours working", lab["unit"], sp_word)), ""]
    L += [f"- {x}" for x in t["deployments"].get(dep, [])] + ["", "# When it was working", ""]
    L += [f"![Hours between the first and last {lab['file']} of each night.]({_png(H.fig_working(n), figs / f'{dep}_working.png')})", ""]
    L += ["# Activity", "",
          f"![{lab['unit'].capitalize()} per hour the device was working, each night"
          + (", with the night's mean temperature below" if "temperature_mean_c" in n else "") + "]("
          + _png(H.fig_activity(n, lab["unit"]), figs / f"{dep}_activity.png") + ")", ""]
    ft = H.fig_temperature(n, lab["unit"])
    if ft:
        L += [f"![Each dot is a night.]({_png(ft, figs / f'{dep}_temperature.png')}){{width=60%}}", ""]
    L += ["# What was recorded", ""]
    if pipe == "images" and len(sp):
        groups = sp.assign(group=sp["kind"].where(sp["kind"] == "other insect", "Moths"))
        groups.loc[groups["kind"] == "other insect", "group"] = groups["taxon"]
        g = groups.groupby("group")["individuals"].sum().sort_values(ascending=False)
        top = g.head(9) if len(g) <= 9 else pd.concat([g.head(8), pd.Series({"all other groups": g.iloc[8:].sum()})])
        L += ["## Insect groups", "",
              f"![Individual insects in each group: moths together, other insects by the order the model gave.]("
              f"{_png(H.fig_bars(list(top.index), list(top.values), 'individual insects'), figs / f'{dep}_groups.png')})", ""]
    if len(main):
        top = main.sort_values("individuals", ascending=False).head(20)
        names = [H._name(r) for r in top.to_dict("records")]
        title = "Moth species" if pipe == "images" else "Species"
        L += [f"## {title}: the 20 most often recorded", "",
              f"![]({_png(H.fig_bars(names, list(top['individuals']), lab['unit']), figs / f'{dep}_species.png')})", "",
              _md_table(pd.DataFrame({"species": names, lab["unit"]: top["individuals"].map("{:,}".format),
                                      "nights": top["nights"], "first": top["first_night"], "last": top["last_night"],
                                      "mean score": top["score_mean"].map(lambda v: f"{v:.2f}" if pd.notna(v) else "")}),
                        right=(lab["unit"], "nights", "mean score")), "",
              f"{len(main):,} {title.lower()} in all: the full list is `{dep}_species.csv` beside this report.", ""]
    L += ["# How this was done", ""] + _methods(t)
    return "\n".join(L)


def project_md(data: Path, t: dict, figs: Path) -> str:
    lab = t["labels"]
    deps = pd.read_parquet(data / "deployments.parquet").sort_values("deployment_id")
    per_hour = (deps["individuals"] / deps["hours_worked"].where(deps["hours_worked"] > 0)).fillna(0)
    L = [f"> {t['methods']['caveat']}", "", "# Summary", ""] + [f"- {x}" for x in t["project_summary"]] + ["",
         "# Deployments", "",
         _md_table(pd.DataFrame({"deployment": deps["deployment_id"], "first night": deps["first_night"],
                                 "last night": deps["last_night"], "nights": deps["nights_worked"],
                                 "hours": deps["hours_worked"].round(0).astype(int),
                                 lab["unit"]: deps["individuals"].map("{:,}".format), "species / groups": deps["taxa"]}),
                   right=("nights", "hours", lab["unit"], "species / groups")), "",
         f"![Average activity per hour working. Deployments ran on different nights and places, so this describes "
         f"them; it doesn't rank them.]({_png(H.fig_bars(list(deps['deployment_id']), list(per_hour.round(1)), lab['unit'] + ' per hour working'), figs / 'project_per_hour.png')})",
         "", "# How this was done", ""] + _methods(t)
    return "\n".join(L)


def front_matter(title: str, subtitle: str, fmt: str, reference_doc: str | None) -> str:
    y = [f'title: "{title}"', f'subtitle: "{subtitle}"', "format:"]
    if fmt == "docx":
        y += ["  docx:", "    toc: false"] + ([f'    reference-doc: "{Path(reference_doc).as_posix()}"'] if reference_doc else [])
    else:
        y += ["  typst:", "    mainfont: Arial", "    fontsize: 10pt", "    margin:", "      x: 2cm", "      y: 2cm"]
    return "---\n" + "\n".join(y) + "\n---\n\n"


WORD_TO_PDF = r"""
$w = New-Object -ComObject Word.Application
$w.Visible = $false; $w.DisplayAlerts = 0
try { $d = $w.Documents.Open($args[0], $false, $true); $d.Fields.Update() | Out-Null
      $d.SaveAs([ref]$args[1], [ref]17); $d.Close([ref]0) } finally { $w.Quit() }
"""


def docx_to_pdf(docx: Path, pdf: Path) -> bool:
    """Word (Windows) or LibreOffice turns a .docx into a PDF. False if neither is there."""
    import os
    if os.name == "nt":
        ps = docx.with_suffix(".ps1")
        ps.write_text(WORD_TO_PDF, encoding="utf-8")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps),
                            str(docx.resolve()), str(pdf.resolve())], capture_output=True, text=True)
        if r.returncode == 0 and pdf.exists():
            return True
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if office:
        subprocess.run([office, "--headless", "--convert-to", "pdf", "--outdir", str(pdf.parent), str(docx)],
                       capture_output=True, text=True)
        made = pdf.parent / (docx.stem + ".pdf")
        if made.exists() and made != pdf:
            made.replace(pdf)
        return pdf.exists()
    return False


def render(md_body: str, title: str, subtitle: str, fmt: str, work: Path, stem: str, out: Path,
           reference_doc: str | None = None) -> Path:
    """One report in one format. PDF: Quarto's own engine (Typst); where that's blocked or missing (some
    managed laptops block it), the Word version is made and converted by Word or LibreOffice."""
    src = work / f"{stem}.qmd"
    src.write_text(front_matter(title, subtitle, fmt, reference_doc) + md_body, encoding="utf-8")
    res = subprocess.run([quarto(), "render", src.name, "--to", FORMATS[fmt]], cwd=work, capture_output=True, text=True)
    made = work / f"{stem}.{'pdf' if fmt == 'pdf' else fmt}"
    if (res.returncode != 0 or not made.exists()) and fmt == "pdf":
        docx = render(md_body, title, subtitle, "docx", work, stem + "_for_pdf", work, reference_doc)
        if docx_to_pdf(docx, made):
            res = None
    if res is not None and (res.returncode != 0 or not made.exists()):
        raise SystemExit(f"Quarto couldn't make the {fmt} report:\n{(res.stderr or res.stdout)[-2000:]}"
                         + ("\nFor PDF, Microsoft Word or LibreOffice also works: neither was found." if fmt == "pdf" else ""))
    target = out / made.name
    if target.resolve() != made.resolve():
        shutil.copy(made, target)
    return target


def make(data: Path, t: dict, formats: list[str], reference_doc: str | None = None) -> list[Path]:
    import tempfile
    out = data.parent
    written = []
    deps = pd.read_parquet(data / "deployments.parquet").set_index("deployment_id")
    with tempfile.TemporaryDirectory(prefix="cehbio_doc_") as tmp:
        work = Path(tmp)
        for fmt in [f for f in formats if f != "html"]:
            for dep in t["deployments"]:
                d = deps.loc[dep]
                sub = f"{t['labels']['what'].capitalize()} · {t['project']}" + (
                    f" · {d.first_night} to {d.last_night}" if isinstance(d.first_night, str) else "")
                written.append(render(deployment_md(data, dep, t, work), dep, sub, fmt, work, dep, out, reference_doc))
                sp = pd.read_parquet(data / "species.parquet")
                if len(sp):
                    sp[sp["deployment_id"] == dep].to_csv(out / f"{dep}_species.csv", index=False)
            if len(t["deployments"]) > 1:
                written.append(render(project_md(data, t, work), t["project"],
                                      f"{t['labels']['what'].capitalize()} · {len(t['deployments'])} deployments",
                                      fmt, work, f"{t['project']}_project", out, reference_doc))
    return written
