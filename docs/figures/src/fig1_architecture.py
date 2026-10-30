"""Figure 1: how a request becomes an answer. Harness components are shaded."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams.update({"font.family": "Helvetica", "font.size": 7.3})
INK, TEAL, PLUM = "#1B262C", "#21808B", "#3E1F5A"
fig, ax = plt.subplots(figsize=(7.2, 3.5))
ax.set_xlim(0, 7.4); ax.set_ylim(-0.25, 3.5); ax.axis("off")
W, H = 1.55, 0.66
box = {}


def node(key, x, y, text, kind="plain"):
    fc = {"plain": "white", "harness": "#E3EEEF", "engine": "#EDE7F2"}[kind]
    ec = {"plain": INK, "harness": TEAL, "engine": PLUM}[kind]
    ax.add_patch(FancyBboxPatch((x - W / 2, y - H / 2), W, H, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=fc, ec=ec, lw=1.0))
    ax.text(x, y, text, ha="center", va="center", color=INK, linespacing=1.25)
    box[key] = (x, y)


def arrow(a, b, label="", rad=0.0, dashed=False, la=(0, 0), sa="c", sb="c"):
    (x1, y1), (x2, y2) = box[a], box[b]
    off = {"c": (0, 0), "l": (-W / 2, 0), "r": (W / 2, 0), "t": (0, H / 2), "b": (0, -H / 2)}
    p1 = (x1 + off[sa][0], y1 + off[sa][1]); p2 = (x2 + off[sb][0], y2 + off[sb][1])
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=9, color=INK, lw=0.9,
                                 connectionstyle=f"arc3,rad={rad}", linestyle="--" if dashed else "-",
                                 shrinkA=1, shrinkB=1))
    if label:
        ax.text((p1[0] + p2[0]) / 2 + la[0], (p1[1] + p2[1]) / 2 + la[1], label, fontsize=7, color=INK,
                ha="center", va="center", style="italic")


node("req", 0.85, 3.1, "Request\n(English or Korean)")
node("llm", 2.75, 3.1, "Language model\n(gpt-6-luna,\ngpt-6.1-terra)")
node("gr", 4.65, 3.1, "Output guardrail:\nnumbers traced to card,\ninputs or request", "harness")
node("ans", 6.55, 3.1, "Answer and\nresults page")
node("sm", 0.85, 1.85, "State machine:\nonly the tools that\nfit the current step", "harness")
node("tree", 2.75, 1.85, "Typed model tree:\ngeometry, physics,\nmaterials, conditions,\nmesh, study", "harness")
node("chk", 4.65, 1.85, "check_model:\nverified configuration,\nresolution rules", "harness")
node("tr", 6.55, 1.85, "Translator:\nmodel tree to\nOpenGeoSys input", "harness")
node("card", 2.75, 0.55, "Answer card:\nvalues computed\nfrom the run", "harness")
node("ver", 4.65, 0.55, "Verification record:\n27 cases: exact solutions,\nbenchmarks, consistency")
node("ogs", 6.55, 0.55, "OpenGeoSys 6.5.8", "engine")

arrow("req", "llm", sa="r", sb="l")
arrow("llm", "gr", "draft answer", sa="r", sb="l", la=(0, 0.42))
arrow("gr", "ans", sa="r", sb="l")
arrow("sm", "tree", "edits", sa="r", sb="l", la=(0, 0.42))
arrow("tree", "chk", sa="r", sb="l")
arrow("chk", "tr", "passed", sa="r", sb="l", la=(0, 0.42))
arrow("tr", "ogs", "run", sa="b", sb="t", la=(0.15, 0))
arrow("ver", "chk", sa="t", sb="b", dashed=True)
ax.add_patch(FancyArrowPatch((6.55, 0.55 - H / 2), (2.75, 0.55 - H / 2), arrowstyle="-|>", mutation_scale=9,
                             color=INK, lw=0.9, connectionstyle="bar,fraction=-0.04", shrinkA=1, shrinkB=1))
ax.text(4.65, 0.0, "outputs", fontsize=7, style="italic", ha="center", va="top")


def path(pts, label=None, at=None):
    xs, ys = zip(*pts)
    ax.plot(xs[:-1] + (xs[-1],), ys[:-1] + (ys[-1],), color=INK, lw=0.9, solid_joinstyle="miter")
    ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=9, color=INK, lw=0.9,
                                 shrinkA=0, shrinkB=1))
    if label:
        ax.text(*at, label, fontsize=7, style="italic", ha="center", va="center")


path([(2.75 + W / 2, 0.55), (3.7, 0.55), (3.7, 2.52), (3.15, 2.52), (3.15, 3.1 - H / 2)], "card", (3.88, 1.2))
path([(2.35, 3.1 - H / 2), (2.35, 2.52), (0.85, 2.52), (0.85, 1.85 + H / 2)], "tool calls", (1.55, 2.62))
ax.add_patch(FancyBboxPatch((0.05, -0.2), 0.22, 0.14, boxstyle="round,pad=0.01", fc="#E3EEEF", ec=TEAL, lw=0.8))
ax.text(0.33, -0.13, "harness", fontsize=7, va="center")
ax.add_patch(FancyBboxPatch((1.05, -0.2), 0.22, 0.14, boxstyle="round,pad=0.01", fc="#EDE7F2", ec=PLUM, lw=0.8))
ax.text(1.33, -0.13, "simulator", fontsize=7, va="center")
fig.savefig("../Figure1_architecture.png", dpi=300, bbox_inches="tight")
