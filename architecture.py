"""Foxhood agent architecture diagram. Run: python architecture.py  ->  architecture.png
Green = implemented, dashed gray = planned."""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

DONE_FILL, DONE_EDGE, DONE_TEXT = "#E1F5EE", "#0F6E56", "#085041"
PLAN_FILL, PLAN_EDGE, PLAN_TEXT = "#F1EFE8", "#888780", "#444441"
GROUP_EDGE, ARROW = "#B4B2A9", "#5F5E5A"

fig, ax = plt.subplots(figsize=(10, 10.6))
ax.set_xlim(0, 680)
ax.set_ylim(720, 0)          # y grows downward, like the original layout
ax.axis("off")


def box(x, y, w, h, title, subtitle, planned=False):
    fill, edge, text = (PLAN_FILL, PLAN_EDGE, PLAN_TEXT) if planned else (DONE_FILL, DONE_EDGE, DONE_TEXT)
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=8",
                                facecolor=fill, edgecolor=edge, linewidth=0.9,
                                linestyle=(0, (4, 3)) if planned else "-"))
    ax.text(x + w / 2, y + h * 0.36, title, ha="center", va="center", fontsize=10.5, weight="bold", color=text)
    ax.text(x + w / 2, y + h * 0.70, subtitle, ha="center", va="center", fontsize=8.5, color=edge)


def group(x, y, w, h, label, dashed=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=16", facecolor="none",
                                edgecolor=GROUP_EDGE, linewidth=0.9, linestyle=(0, (4, 3)) if dashed else "-"))
    ax.text(x + 18, y + 18, label, ha="left", va="center", fontsize=10.5, weight="bold", color="#2C2C2A")


def arrow(points, dashed=False):
    for (x1, y1), (x2, y2) in zip(points[:-2], points[1:-1]):     # straight segments of an L-shaped path
        ax.plot([x1, x2], [y1, y2], color=ARROW, linewidth=1.1, linestyle="--" if dashed else "-")
    ax.add_patch(FancyArrowPatch(points[-2], points[-1], arrowstyle="-|>", mutation_scale=11, color=ARROW,
                                 linewidth=1.1, linestyle="--" if dashed else "-", shrinkA=0, shrinkB=0))


# Front end and API
box(120, 30, 200, 56, "Next.js web app", "Google sign-in, dashboard")
box(360, 30, 200, 56, "Chat page", "Live streaming UI", planned=True)
arrow([(220, 86), (220, 119)])
arrow([(460, 86), (460, 119)], dashed=True)
box(120, 120, 440, 56, "FastAPI backend", "Auth, event streaming, daily spend caps")
arrow([(340, 176), (340, 205)])

# Agent loop
group(40, 206, 600, 150, "Agent loop (LangGraph)")
loop = [("Agent (Haiku)", "Picks next step"), ("Permission gate", "Allow, ask, deny"),
        ("Approval pause", "User says yes/no"), ("Tools node", "Runs in parallel")]
xs = [58, 203, 348, 493]
for x, (title, sub) in zip(xs, loop):
    box(x, 250, 130, 56, title, sub)
for x in xs[:-1]:
    arrow([(x + 130, 278), (x + 145, 278)])
arrow([(558, 306), (558, 334), (123, 334), (123, 307)])        # loop back until the agent answers
arrow([(340, 356), (340, 385)])

# What the tools node calls
group(40, 386, 600, 96, "Called by the tools node")
for x, (title, sub) in zip(xs, [("Data tools", "Prices, portfolio"), ("News subagent", "Own loop + cache"),
                                ("Skills", "3 SKILL.md guides"), ("MCP server", "FRED macro data")]):
    box(x, 416, 130, 56, title, sub)

# Storage
box(58, 500, 275, 56, "Memory", "Encrypted Postgres: notes + chats")
box(348, 500, 275, 56, "Tracing", "Every step logged, cost tracked")

# Planned
group(40, 576, 600, 100, "Planned (M3 to M6)", dashed=True)
for x, (title, sub) in zip(xs, [("Fact-checker", "Second subagent"), ("What-if tool", "Scenario tests"),
                                ("Earnings tool", "Earnings calendar"), ("Auto briefs", "Email + alerts")]):
    box(x, 608, 130, 56, title, sub, planned=True)

# Legend
ax.add_patch(FancyBboxPatch((220, 692), 14, 12, boxstyle="round,pad=0,rounding_size=3",
                            facecolor=DONE_FILL, edgecolor=DONE_EDGE, linewidth=0.9))
ax.text(242, 698, "Implemented", va="center", fontsize=9, color="#444441")
ax.add_patch(FancyBboxPatch((360, 692), 14, 12, boxstyle="round,pad=0,rounding_size=3", facecolor=PLAN_FILL,
                            edgecolor=PLAN_EDGE, linewidth=0.9, linestyle=(0, (3, 2))))
ax.text(382, 698, "Planned", va="center", fontsize=9, color="#444441")

plt.tight_layout()
plt.savefig("architecture.png", dpi=200, bbox_inches="tight", facecolor="white")
print("Saved architecture.png")