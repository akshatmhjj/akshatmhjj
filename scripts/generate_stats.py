#!/usr/bin/env python3
"""Draw the profile README's stat graphics from the GitHub GraphQL API.

No third-party services and no dependencies — standard library only.

Outputs:
  contrib-heatmap.svg  the year as GitHub's green grid, revealed cell by cell
  stats.svg            terminal-window numbers card, the same size as the
                       portrait window (ascii.svg) so the two sit side by side

and, sharing one visual language with the portrait's grey ink:
  streak.svg  current and longest streak
  langs.svg   top languages, by bytes and by repo count
  year.svg    the year as a character map, in the portrait's own ramp

The ink graphics use the portrait's grey ink, a monospace face, a transparent
background, and the same left-to-right clipPath reveal with a cursor riding
the edge. Motion is SMIL because GitHub strips <script> from READMEs.

Env:
    GITHUB_TOKEN  required; use a user token with private-repository access for
                                profile-accurate totals
  GH_LOGIN      user to summarise (default: andriidrok1)
  OUT_DIR       where to write (default: repository root)
"""
import base64
import functools
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://api.github.com/graphql"

# Two things are pinned for determinism, both learned the hard way:
#  * the contribution window, to whole UTC days — otherwise "the past year" is
#    measured from request time and days drift between week buckets, moving the
#    sparkline a fraction of a pixel and committing noise every night;
#  * privacy: private contributions are requested explicitly. GitHub only
#    returns them when the token belongs to the profile owner and can see the
#    relevant repositories; the workflow documents that token requirement.
QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount contributionLevel date weekday } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

# The portrait's ink is the data ink, so every graphic reads as one material.
LIGHT = dict(data="#6e7681", emph="#424a53", dim="#8c959f",
             rule="#d8dee4", surface="#ffffff")
DARK = dict(data="#c9d1d9", emph="#f0f6fc", dim="#8b949e",
            rule="#30363d", surface="#0d1117")
# JBMono is the inlined subset below; the rest is a fallback for the unlikely
# case a renderer ignores the embedded face.
MONO = ("JBMono,ui-monospace,SFMono-Regular,Menlo,Consolas,"
        "&apos;Liberation Mono&apos;,monospace")
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


@functools.lru_cache(maxsize=None)
def face(filename, weight):
    """One @font-face rule with the subset inlined as a data URI.

    An external font URL cannot work here: these SVGs are loaded through <img>,
    and browsers refuse to fetch subresources for an image document. Inlining is
    also what pins the advance width — the portrait's grid assumes 0.600 em, and
    a viewer whose default monospace is narrower would otherwise see it squeezed.
    """
    with open(os.path.join(FONT_DIR, filename), "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return (f"@font-face{{font-family:JBMono;font-style:normal;"
            f"font-weight:{weight};font-display:block;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")


def font_text():
    """Basic latin, both weights — for the data graphics."""
    return face("jbmono-400.woff2", 400) + face("jbmono-600.woff2", 600)


def font_head():
    """Only the letters the section headings use."""
    return face("jbmono-head.woff2", 600)

WIDTH = 620            # every graphic shares one column width
LEFT = 34              # shared left inset, so stacked blocks line up
                       # (year.svg needs it for the weekday gutter)
REVEAL = 1.30          # seconds; matches the portrait's cadence
RAMP = [" ", ":", "+", "#", "@"]      # steps of the portrait's own ramp
MON = ["jan", "feb", "mar", "apr", "may", "jun",
       "jul", "aug", "sep", "oct", "nov", "dec"]


# ---------------------------------------------------------------- data

def window():
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    return (f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z")


def fetch(login, token):
    since, until = window()
    body = json.dumps({"query": QUERY,
                       "variables": {"login": login,
                                     "from": since, "to": until}}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": f"bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": f"{login}-profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(f"GraphQL errors: {payload['errors']}")
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise SystemExit(f"no such user: {login}")
    return user


def pretty(iso):
    d = date.fromisoformat(iso)
    return f"{MON[d.month - 1]} {d.day}"


def streaks(days):
    """Current and longest runs of days with at least one contribution.

    A zero on the final day doesn't break the current streak — the day isn't
    over yet. Any earlier zero does.
    """
    best = dict(length=0, start=None, end=None)
    run, run_start = 0, None
    for d in days:
        if d["contributionCount"] > 0:
            run += 1
            run_start = run_start or d["date"]
            if run > best["length"]:
                best = dict(length=run, start=run_start, end=d["date"])
        else:
            run, run_start = 0, None

    cur = dict(length=0, start=None, end=None)
    tail = days[:-1] if days and days[-1]["contributionCount"] == 0 else days
    for d in reversed(tail):
        if d["contributionCount"] == 0:
            break
        cur["length"] += 1
        cur["start"] = d["date"]
        cur["end"] = cur["end"] or d["date"]
    return cur, best


def languages(repos):
    by_size, by_repo = {}, {}
    for node in repos:
        edges = (node.get("languages") or {}).get("edges") or []
        for e in edges:
            name = e["node"]["name"]
            by_size[name] = by_size.get(name, 0) + e["size"]
        if edges:                       # primary language of the repo
            top = edges[0]["node"]["name"]
            by_repo[top] = by_repo.get(top, 0) + 1

    def rank(d):
        # sort by value, then name, so equal values never reorder between runs
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    return rank(by_size), rank(by_repo)


def summarise(user):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in cal["weeks"]]
    days = [d for w in weeks for d in w]
    cur, best = streaks(days)
    by_size, by_repo = languages(user["repositories"]["nodes"])
    active = sum(1 for d in days if d["contributionCount"] > 0)
    monthly = {}
    for d in days:
        monthly[d["date"][:7]] = (monthly.get(d["date"][:7], 0)
                                  + d["contributionCount"])
    # the earliest of equal days, so a tie never flips between runs
    top_day = max(days, key=lambda d: d["contributionCount"]) if days else None
    return dict(
        total=cal["totalContributions"],
        active=active, n_days=len(days),
        avg=round(cal["totalContributions"] / active, 1) if active else 0.0,
        best_day=top_day, monthly=sorted(monthly.items()),
        weeks=weeks,
        current=cur, longest=best,
        by_size=by_size, by_repo=by_repo)


# ---------------------------------------------------------------- drawing

def style(extra="", font=None):
    def block(t):
        return (f".d-f{{fill:{t['data']}}}.d-s{{stroke:{t['data']}}}"
                f".e-f{{fill:{t['emph']}}}.m-f{{fill:{t['dim']}}}"
                f".u-s{{stroke:{t['rule']}}}.r{{stroke:{t['surface']}}}")
    return (f"<style>{font or font_text()}"
            f"{block(LIGHT)}.w{{fill:{LIGHT['data']};opacity:.13}}{extra}"
            f"@media(prefers-color-scheme:dark){{{block(DARK)}"
            f".w{{fill:{DARK['data']};opacity:.16}}}}</style>")


def head(w, h, font=None):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" fill="none" font-family="{MONO}">'
            + style(font=font))


def fade(delay, dur=0.45):
    return (f'<animate attributeName="opacity" from="0" to="1" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>')


def wipe(cid, x, y, w, h, delay, dur=REVEAL):
    """clipPath reveal plus the cursor block that rides its edge."""
    clip = (f'<clipPath id="{cid}"><rect x="{x}" y="{y}" height="{h}" width="0">'
            f'<animate attributeName="width" from="0" to="{w}" '
            f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/></rect></clipPath>')
    cursor = (f'<rect y="{y}" width="2" height="{h}" class="d-f" opacity="0">'
              f'<animate attributeName="x" from="{x}" to="{x + w}" '
              f'begin="{delay:.2f}s" dur="{dur}s" fill="freeze"/>'
              f'<set attributeName="opacity" to="0.55" begin="{delay:.2f}s"/>'
              f'<set attributeName="opacity" to="0" '
              f'begin="{delay + dur:.2f}s"/></rect>')
    return clip, cursor


def label(x, y, text, size=11, cls="m-f", anchor="start", extra=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}"{a}'
            f'{extra}>{text}</text>')


def hbar(x, y, w, h, cls="d-f", r=3.0):
    """Horizontal bar: rounded data-end on the right, square at the baseline."""
    if w <= 0.6:
        return ""
    r = min(r, h / 2.0, w)
    return (f'<path d="M{x:.1f} {y:.1f}H{x + w - r:.1f}'
            f'Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}'
            f'V{y + h - r:.1f}Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}'
            f'H{x:.1f}Z" class="{cls}"/>')


# The two terminal windows at the top (portrait + numbers) share one canvas, so
# equal <img> widths in the README give equal heights. make_portrait.py imports
# these. The windows stay dark in both themes, like a real terminal would.
CARD_W, CARD_H = 840, 880
TERM = dict(bg="#0d1117", bg2="#111722", tile="#161b22", frame="#30363d",
            dim="#7d8590", ink="#e6edf3", green="#39d353", bar="#26a641")
PROMPT = "akshat@github"


def terminal(w, h, title, titlebar=30, pad=20):
    """Window chrome: dark body, hairline frame, traffic lights, title."""
    p = [f'<defs><linearGradient id="tbg" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0" stop-color="{TERM["bg2"]}"/>'
         f'<stop offset="1" stop-color="{TERM["bg"]}"/></linearGradient></defs>',
         f'<rect width="{w}" height="{h}" rx="12" fill="url(#tbg)"/>',
         f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="12" '
         f'fill="none" stroke="{TERM["frame"]}"/>',
         f'<line x1="0" y1="{titlebar}" x2="{w}" y2="{titlebar}" '
         f'stroke="{TERM["frame"]}"/>']
    for i, dot in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        p.append(f'<circle cx="{pad + i * 16}" cy="{titlebar / 2}" r="5" '
                 f'fill="{dot}"/>')
    p.append(f'<text x="{w / 2}" y="{titlebar / 2 + 4}" fill="{TERM["dim"]}" '
             f'font-size="12" text-anchor="middle">{title}</text>')
    return p


# GitHub's own ramps, light and dark, indexed by contributionLevel
HEAT_LIGHT = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
HEAT_DARK = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
LEVEL = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
         "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def draw_heatmap(s):
    """The contribution calendar as boxes that pop in on a diagonal sweep.

    CSS keyframes rather than SMIL here: one rule animates all ~370 cells and
    the per-cell delay is a single style attribute, which keeps the file small.
    GitHub runs CSS animation inside <img> SVGs, it only strips scripts.
    """
    CELL, GAP, RAD, LX, TOP = 13, 3, 2.5, 34, 24
    STEP = CELL + GAP
    REVEAL_T, DUR = 3.6, 0.55
    weeks = s["weeks"]
    nw = len(weeks)
    W = LX + nw * STEP + 4
    H = TOP + 7 * STEP + 24
    span = max((nw - 1) + 6 * 0.55, 1)

    def palette(colors):
        return "".join(f".l{i}{{fill:{c}}}" for i, c in enumerate(colors))

    css = (f".c{{transform-box:fill-box;transform-origin:center;opacity:0;"
           f"animation:pop {DUR}s ease-out both}}"
           f".g{{animation:pop {DUR}s ease-out both,"
           f"flash {DUR + 0.15:.2f}s ease-out both}}"
           "@keyframes pop{0%{opacity:0;transform:scale(.2)}"
           "60%{opacity:1;transform:scale(1.1)}"
           "100%{opacity:1;transform:scale(1)}}"
           "@keyframes flash{0%,45%{filter:brightness(2.2)}"
           "100%{filter:brightness(1)}}"
           "@media(prefers-reduced-motion:reduce){.c{opacity:1!important;"
           "animation:none!important}}"
           + palette(HEAT_LIGHT)
           + f"@media(prefers-color-scheme:dark){{{palette(HEAT_DARK)}}}")

    p = [head(W, H).replace("</style>", css + "</style>")]
    last_m, last_x = None, -999.0
    for wi, w in enumerate(weeks):
        m = int(w[0]["date"][5:7])
        x = LX + wi * STEP
        if m != last_m and x - last_x >= 30 and wi < nw - 2:
            p.append(label(x, TOP - 9, MON[m - 1], 11, "m-f"))
            last_x = x
        last_m = m
    for r, lab in ((1, "mon"), (3, "wed"), (5, "fri")):
        p.append(label(0, TOP + r * STEP + CELL - 3, lab, 10, "m-f"))

    for wi, w in enumerate(weeks):
        for d in w:
            r = d["weekday"]
            lvl = LEVEL.get(d.get("contributionLevel"),
                            1 if d["contributionCount"] else 0)
            delay = (wi + r * 0.55) / span * REVEAL_T
            n = d["contributionCount"]
            p.append(f'<rect class="c{" g" if lvl else ""} l{lvl}" '
                     f'x="{LX + wi * STEP}" y="{TOP + r * STEP}" '
                     f'width="{CELL}" height="{CELL}" rx="{RAD}" '
                     f'style="animation-delay:{delay:.2f}s">'
                     f'<title>{d["date"]}: {n} contribution'
                     f'{"" if n == 1 else "s"}</title></rect>')

    p.append(label(LX, H - 4, f'{s["total"]:,} contributions in the last year',
                   13, "e-f", extra=' font-weight="600"'))
    lx = W - 32 - 5 * (CELL + 2)          # room for "more" after the swatches
    p.append(label(lx - 6, H - 5, "less", 10, "m-f", "end"))
    for i in range(5):
        p.append(f'<rect class="l{i}" x="{lx + i * (CELL + 2)}" y="{H - 15}" '
                 f'width="{CELL - 2}" height="{CELL - 2}" rx="2"/>')
    p.append(label(lx + 5 * (CELL + 2) + 4, H - 5, "more", 10, "m-f"))
    p.append("</svg>")
    return "".join(p)


def draw_card(s):
    """Six numbers that count up, then contributions per month as bars.

    The count-up is a stack of pre-rendered frames toggled with SMIL <set>,
    since GitHub runs SMIL and CSS inside <img> SVGs but never JS.
    """
    W, H, PAD, TB = CARD_W, CARD_H, 20, 30
    COLS, ROWS, GAP, TILE_H = 2, 3, 16, 150
    TILE_W = (W - PAD * 2 - GAP * (COLS - 1)) / COLS
    TILES_TOP = TB + PAD + 4
    CHART_TOP = TILES_TOP + ROWS * TILE_H + (ROWS - 1) * GAP + GAP
    STAGGER, SLIDE, COUNT, FRAMES = 0.15, 0.45, 1.2, 16
    BAR_START = STAGGER * COLS * ROWS + 0.4
    BAR_STAGGER, BAR_DUR = 0.06, 0.6
    t = TERM

    def span(r):
        return (f"{pretty(r['start'])} &#8211; {pretty(r['end'])}"
                if r["length"] else "&#8212;")

    bd = s["best_day"]
    share = s["active"] / s["n_days"] if s["n_days"] else 0
    tiles = [
        ("current streak", s["current"]["length"], " days",
         span(s["current"]), t["green"]),
        ("longest streak", s["longest"]["length"], " days",
         span(s["longest"]), t["ink"]),
        ("contributions", s["total"], "", "in the last year", t["ink"]),
        ("active days", s["active"], f" / {s['n_days']}",
         f"{share:.0%} of the year", t["ink"]),
        ("best day", bd["contributionCount"] if bd else 0, "",
         pretty(bd["date"]) if bd else "&#8212;", t["ink"]),
        ("avg / active day", s["avg"], "", "contributions", t["ink"]),
    ]

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="{MONO}">'
         f'<style>{font_text()}'
         f'.t{{opacity:0;animation:in {SLIDE}s ease-out both}}'
         '@keyframes in{0%{opacity:0;transform:translateY(14px)}'
         '100%{opacity:1;transform:translateY(0)}}'
         f'.b{{transform-box:fill-box;transform-origin:bottom;'
         f'transform:scaleY(0);animation:grow {BAR_DUR}s ease-out both}}'
         '@keyframes grow{to{transform:scaleY(1)}}'
         '@media(prefers-reduced-motion:reduce){.t,.b{opacity:1!important;'
         'transform:none!important;animation:none!important}}</style>']
    p += terminal(W, H, f"{PROMPT}: ~$ ./stats.sh", TB, PAD)

    for i, (lab, value, suffix, caption, accent) in enumerate(tiles):
        x = PAD + (i % COLS) * (TILE_W + GAP)
        y = TILES_TOP + (i // COLS) * (TILE_H + GAP)
        start = i * STAGGER
        count_start = start + SLIDE * 0.6
        p.append(f'<g class="t" style="animation-delay:{start:.2f}s">'
                 f'<rect x="{x:.1f}" y="{y}" width="{TILE_W:.1f}" '
                 f'height="{TILE_H}" rx="10" fill="{t["tile"]}" '
                 f'stroke="{t["frame"]}"/>'
                 f'<text x="{x + 24:.1f}" y="{y + 40}" fill="{t["dim"]}" '
                 f'font-size="22">$ {lab}</text>')
        for k in range(1, FRAMES + 1):
            q = k / FRAMES
            v = value * (1 - (1 - q) ** 3)        # ease out into the real value
            shown = (f"{v:,.1f}" if isinstance(value, float)
                     else f"{int(round(v)):,}")
            on = count_start + COUNT * (k - 1) / FRAMES
            anim = f'<set attributeName="opacity" to="1" begin="{on:.3f}s"/>'
            if k < FRAMES:
                off = count_start + COUNT * k / FRAMES
                anim += (f'<set attributeName="opacity" to="0" '
                         f'begin="{off:.3f}s"/>')
            p.append(f'<text x="{x + 24:.1f}" y="{y + 100}" opacity="0" '
                     f'font-size="54" font-weight="600" fill="{accent}">'
                     f'{shown}<tspan font-size="24" font-weight="400" '
                     f'fill="{t["dim"]}">{suffix}</tspan>{anim}</text>')
        p.append(f'<text x="{x + 24:.1f}" y="{y + 132}" fill="{t["dim"]}" '
                 f'font-size="20">{caption}</text></g>')

    monthly = s["monthly"] or [("2000-01", 0)]
    cx, cw = PAD, W - PAD * 2
    ch = H - PAD - CHART_TOP
    p.append(f'<g class="t" style="animation-delay:{BAR_START - 0.3:.2f}s">'
             f'<rect x="{cx}" y="{CHART_TOP}" width="{cw}" height="{ch}" '
             f'rx="10" fill="{t["tile"]}" stroke="{t["frame"]}"/>'
             f'<text x="{cx + 24}" y="{CHART_TOP + 40}" fill="{t["dim"]}" '
             f'font-size="22">$ contributions / month</text></g>')
    top, bot = CHART_TOP + 72, CHART_TOP + ch - 40
    left, right = cx + 24, cx + cw - 24
    slot = (right - left) / len(monthly)
    bw = slot * 0.62
    peak = max(v for _, v in monthly) or 1
    for i, (month, total) in enumerate(monthly):
        h = max(2, (bot - top) * total / peak)
        bx = left + i * slot + (slot - bw) / 2
        delay = BAR_START + i * BAR_STAGGER
        hot = total == peak and total > 0
        p.append(f'<rect class="b" x="{bx:.1f}" y="{bot - h:.1f}" '
                 f'width="{bw:.1f}" height="{h:.1f}" rx="3" '
                 f'fill="{t["green"] if hot else t["bar"]}" '
                 f'style="animation-delay:{delay:.2f}s"/>')
        p.append(f'<text x="{bx + bw / 2:.1f}" y="{bot + 28}" '
                 f'fill="{t["dim"]}" font-size="18" text-anchor="middle">'
                 f'{MON[int(month[5:7]) - 1][0]}</text>')
        if hot:
            p.append(f'<text class="t" style="animation-delay:'
                     f'{delay + BAR_DUR:.2f}s" x="{bx + bw / 2:.1f}" '
                     f'y="{bot - h - 10:.1f}" fill="{t["ink"]}" font-size="18" '
                     f'text-anchor="middle">{peak:,}</text>')
    p.append("</svg>")
    return "".join(p)


def draw_streak(s):
    """Current and longest streak, split by a hairline."""
    H = 96
    cells = []
    for k, lab in (("current", "current streak"), ("longest", "longest streak")):
        r = s[k]
        span = (f"{pretty(r['start'])} &#8211; {pretty(r['end'])}"
                if r["length"] else "&#8212;")
        cells.append((r["length"], lab, span))

    p = [head(WIDTH, H)]
    mid = WIDTH / 2
    p.append(f'<line x1="{mid:.0f}" y1="16" x2="{mid:.0f}" y2="80" '
             f'class="u-s" stroke-width="1" opacity="0">{fade(0.20)}</line>')
    for i, (val, lab, span) in enumerate(cells):
        x = LEFT if i == 0 else mid + LEFT
        p.append(f'<g opacity="0">{fade(0.12 + i * 0.14)}'
                 + label(x, 44, f"{val}", 34, "e-f", extra=' font-weight="600"')
                 + label(x, 64, lab, 11)
                 + label(x, 80, span, 10) + '</g>')
    p.append("</svg>")
    return "".join(p)


def draw_langs(s):
    """Two small charts: share of bytes, and count of repos by main language."""
    rows = max(len(s["by_size"]), len(s["by_repo"]), 1)
    H = 26 + rows * 22 + 6
    colw = (WIDTH - LEFT - 30) / 2
    name_w, bar_max = 82, colw - 82 - 44

    p = [head(WIDTH, H)]
    groups = [(LEFT, "by bytes", s["by_size"], True),
              (LEFT + colw + 30, "by repos", s["by_repo"], False)]
    for gi, (gx, title, data, as_pct) in enumerate(groups):
        p.append(f'<g opacity="0">{fade(0.10 + gi * 0.10)}'
                 + label(gx, 12, title.upper(), 9, "m-f",
                         extra=' letter-spacing="1.3"') + '</g>')
        if not data:
            continue
        top = max(v for _, v in data) or 1
        total = sum(v for _, v in data) or 1
        cid = f"rl{gi}"
        clip, cursor = wipe(cid, gx + name_w, 20, bar_max, rows * 22,
                            0.34 + gi * 0.12, 0.95)
        p.append(clip)
        for ri, (name, val) in enumerate(data):
            y = 26 + ri * 22
            shown = (f"{val / total * 100:.0f}%" if as_pct else f"{val}")
            p.append(f'<g opacity="0">{fade(0.24 + gi * 0.10 + ri * 0.05)}'
                     + label(gx, y + 8, name.lower()[:11], 11, "e-f")
                     + label(gx + colw - 6, y + 8, shown, 11, "m-f", "end")
                     + '</g>')
            p.append(f'<g clip-path="url(#{cid})">'
                     + hbar(gx + name_w, y, bar_max * val / top, 7)
                     + '</g>')
        p.append(cursor)
    p.append("</svg>")
    return "".join(p)


def draw_heading(word):
    """A section heading in the mono face, with a hairline running right.

    GitHub strips <style> and style= from markdown, so a real markdown heading
    can only ever be GitHub's own sans. Rendering the label as an SVG is the
    only way to put the page's own typeface on it. The rule starts past the
    longest plausible advance (0.6em is the widest common monospace ratio), so
    a narrower font on the viewer's machine widens the gap slightly rather than
    colliding with the text.
    """
    FS = 16
    H = 26
    text_end = len(word) * FS * 0.6 + 18
    p = [head(WIDTH, H, font=font_head())]
    p.append(label(0, 18, word, FS, "e-f", extra=' font-weight="600"'))
    p.append(f'<line x1="{text_end:.0f}" y1="12.5" x2="{WIDTH}" y2="12.5" '
             f'class="u-s" stroke-width="1"/>')
    p.append("</svg>")
    return "".join(p)


def draw_year(s):
    """Seven rows by fifty-three weeks, intensity as a character."""
    FS, LH, COLW = 9.2, 11.0, 2
    CW = FS * 0.6
    pad_l, pad_t = LEFT, 44
    weeks = s["weeks"]
    ncols = len(weeks) * COLW
    H = int(pad_t + 7 * LH + 26)

    def level(v):
        for i, cut in enumerate((0, 2, 5, 9)):
            if v <= cut:
                return i
        return 4

    p = [head(WIDTH, H)]
    p.append(f'<g opacity="0">{fade(0.10)}'
             + label(pad_l, 16, "THE YEAR", 9, "m-f",
                     extra=' letter-spacing="1.3"')
             + label(pad_l, 32, f"{s['active']} of "
                     f"{sum(len(w) for w in weeks)} days had a contribution", 11)
             + '</g>')

    # ramp legend, so the encoding is never carried by shade alone
    lx = WIDTH - 6
    p.append(f'<g opacity="0">{fade(1.30)}'
             + label(lx - 78, 32, "less", 9, "m-f", "end")
             + f'<text xml:space="preserve" x="{lx - 72}" y="32" class="d-f" '
             f'font-size="{FS}">{" ".join(RAMP[1:])}</text>'
             + label(lx, 32, "more", 9, "m-f", "end") + '</g>')

    for r in range(7):
        chars = []
        for w in weeks:
            day = next((d for d in w if d.get("weekday") == r), None)
            v = day["contributionCount"] if day else 0
            chars.append(RAMP[level(v)] * COLW)
        line = "".join(chars).rstrip()
        if not line:
            continue
        y = pad_t + r * LH
        w_px = max(len(line), 1) * CW
        cid = f"ry{r}"
        delay = 0.30 + r * 0.07
        p.append(f'<clipPath id="{cid}"><rect x="{pad_l}" y="{y}" '
                 f'height="{LH}" width="0"><animate attributeName="width" '
                 f'from="0" to="{w_px:.1f}" begin="{delay:.2f}s" dur="0.40s" '
                 f'fill="freeze"/></rect></clipPath>')
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        p.append(f'<g clip-path="url(#{cid})"><text xml:space="preserve" '
                 f'x="{pad_l}" y="{y + FS - 0.6:.1f}" class="d-f" '
                 f'font-size="{FS}">{safe}</text></g>')

    for r, lab in ((1, "mon"), (3, "wed"), (5, "fri")):
        p.append(label(pad_l - 7, pad_t + r * LH + FS - 0.6, lab, 9, "m-f",
                       "end"))

    last_m, last_x = None, -999.0
    base_y = pad_t + 7 * LH + 13
    for i, w in enumerate(weeks):
        m = int(w[0]["date"][5:7])
        x = pad_l + i * COLW * CW
        if m != last_m and i < len(weeks) - 1 and x - last_x >= 34:
            p.append(label(x, base_y, MON[m - 1], 9, "m-f"))
            last_x = x
        last_m = m

    p.append("</svg>")
    return "".join(p)


# ---------------------------------------------------------------- main

def write(path, svg):
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old == svg:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return True


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    login = os.environ.get("GH_LOGIN", "andriidrok1")
    out_dir = os.environ.get("OUT_DIR", ".")

    s = summarise(fetch(login, token))
    files = {"contrib-heatmap.svg": draw_heatmap(s), "stats.svg": draw_card(s),
             "streak.svg": draw_streak(s),
             "langs.svg": draw_langs(s), "year.svg": draw_year(s)}
    for word in ("about", "stack", "projects", "stats", "about this page"):
        files[f"hd-{word.replace(' ', '-')}.svg"] = draw_heading(word)

    changed = [n for n, svg in files.items()
               if write(os.path.join(out_dir, n), svg)]
    print(f"{s['total']} contributions, {s['active']} active days, "
          f"best day {(s['best_day'] or {}).get('contributionCount', 0)}, "
          f"current streak "
          f"{s['current']['length']}, longest {s['longest']['length']}")
    print("languages by bytes: "
          + ", ".join(f"{n} {v}" for n, v in s["by_size"]))
    print("updated: " + (", ".join(sorted(changed)) if changed else "nothing"))


if __name__ == "__main__":
    main()
