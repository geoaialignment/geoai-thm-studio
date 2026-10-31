"""One figure style for every picture the harness draws (result maps, profiles, series, mesh previews).

Figures are sized close to how they are shown (about 6.5 in wide in a chat or report) and saved at 200 dpi, so text
stays readable on screen and in print. Layout is constrained so that titles, labels, legends and colour bars never
overlap the plot. Each quantity has its own one-hue colour scale (light = low, dark = high); lines use a fixed
categorical order.
"""
from __future__ import annotations

import textwrap

DPI = 200
WIDTH = 6.5  # inches
INK, MUTED, GRID = "#1B262C", "#52616A", "#D6DCDB"
STYLE = {
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11.5,
    "xtick.labelsize": 10.5,
    "ytick.labelsize": 10.5,
    "legend.fontsize": 10,
    "figure.titlesize": 12,
    "text.color": INK,
    "axes.labelcolor": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.titlelocation": "left",
    "axes.titlepad": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#8A979C",
    "axes.linewidth": 0.8,
    "lines.linewidth": 2.0,
    "lines.markersize": 5,
    "xtick.direction": "out",
    "ytick.direction": "out",
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "legend.frameon": False,
    "figure.constrained_layout.use": True,
    "savefig.dpi": DPI,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.08,
    "figure.dpi": 100,
}
# fixed categorical order for lines (times, cases); never cycled beyond its length
LINES = ["#21808B", "#C2552F", "#3E3F83", "#7A9A2E", "#8E4C8E", "#B08A1E", "#4E6E8E", "#6B6B6B"]
# one-hue ramps, light to dark
RAMPS = {
    "temperature": ["#FBF7F1", "#F6E1C4", "#EFBE8E", "#E3925C", "#CC6138", "#A23A22", "#6B1E14"],
    "hydraulic": ["#F3F7FA", "#D4E3EE", "#A9C7DE", "#729FC6", "#4777A8", "#28507E", "#132F52"],
    "concentration": ["#F4F4F8", "#D9DAEC", "#AFB2DA", "#8086C2", "#5A5FA6", "#3E3F83", "#26245A"],
    "mechanics": ["#F5F6F2", "#DDE3D3", "#BCCAA8", "#93AE79", "#6A8D52", "#486A36", "#2C4520"],
    "default": ["#F2F6F5", "#CFE5E3", "#93C9C6", "#4FA6A8", "#21808B", "#15596A", "#0E3640"],
}
FIELD_RAMP = {"temperature": "temperature", "heat_flux": "temperature", "head": "hydraulic", "pressure": "hydraulic",
              "darcy_velocity": "hydraulic", "displacement": "mechanics", "sigma": "mechanics", "epsilon": "mechanics"}


def pyplot():
    """matplotlib.pyplot with the Agg backend and the harness style applied."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update(STYLE)
    return plt


def cmap_for(name: str):
    """One-hue colour scale for a field name (unknown names, e.g. solute components, use the concentration ramp)."""
    from matplotlib.colors import LinearSegmentedColormap
    key = FIELD_RAMP.get(name, "concentration" if name not in ("",) else "default")
    return LinearSegmentedColormap.from_list(key, RAMPS[key])


def wrap(text: str, width: int = 58) -> str:
    """Break a long title into lines so it never runs past the figure."""
    return "\n".join(textwrap.wrap(text, width)) or text
