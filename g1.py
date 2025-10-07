import numpy as np
import matplotlib.pyplot as plt

# --- 1. DEFINE METRICS AND SAMPLE DATA ---
# These are the axes for our radar chart
labels = ['Total P&L ($)', 'Sharpe Ratio', 'Max Drawdown (%)']
num_vars = len(labels)

# Plausible sample data for three strategies
# [P&L, Sharpe, Drawdown] - Note: Drawdown is inverted for the plot (lower is better)
data = {
    'Triangular Arbitrage': [15000, 2.5, 1 - 0.05],  # Low P&L, high Sharpe, low risk
    'Pairs Trading':        [75000, 1.8, 1 - 0.15],  # Medium P&L, good Sharpe, medium risk
    'Latency Arbitrage':    [120000, 0.9, 1 - 0.25]   # High P&L, low Sharpe, high risk
}
# We invert drawdown so that a larger area is always better on the chart.

# --- 2. RADAR CHART SETUP ---
# Calculate angles for each axis
angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
angles += angles[:1] # complete the loop

# --- 3. VISUALIZATION ---
fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
plt.style.use('seaborn-v0_8-darkgrid')

# Helper function to plot each strategy
def add_to_radar(strategy_name, values, color):
    # The first value must be repeated at the end to close the polygon
    plot_values = values + values[:1]
    ax.plot(angles, plot_values, color=color, linewidth=2, linestyle='solid', label=strategy_name)
    ax.fill(angles, plot_values, color=color, alpha=0.25)

# Plot each strategy
colors = ['#27C281', '#4098FF', '#FFC300']
for (strategy, values), color in zip(data.items(), colors):
    # Normalize data for plotting on a common scale (0-1)
    # This is a simplified normalization for visualization purposes.
    normalized_values = [
        values[0] / 150000, # P&L normalized to a max of $150k
        values[1] / 3.0,      # Sharpe normalized to a max of 3.0
        values[2] / 1.0       # Drawdown is already 0-1
    ]
    add_to_radar(strategy, normalized_values, color)

# --- 4. FORMATTING ---
ax.set_yticklabels([]) # Hide the radial labels
ax.set_xticks(angles[:-1])
ax.set_xticklabels(labels, size=12)

plt.title('Strategy Performance Profile: Alpha vs. Risk', size=20, color='white', y=1.1)
ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))

# Add a text box explaining the result
summary_text = (f'Insight:\n'
                f'- Pairs Trading shows the most balanced profile.\n'
                f'- Triangular Arbitrage is highly risk-averse.\n'
                f'- Latency Arbitrage is a high-risk, high-reward "hero" strategy.')
fig.text(0.5, 0.01, summary_text, ha='center', va='bottom', fontsize=12, bbox=dict(boxstyle="round,pad=0.5", fc='yellow', alpha=0.3))


plt.show()