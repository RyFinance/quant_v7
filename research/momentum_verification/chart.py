from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np, pandas as pd
import research.momentum_verification.benchmarks as bm

OUT = Path('reports/momentum_verification_20260919')
SERIES = [
    ('Frozen rule, survivor universe', bm.nav_returns(OUT/'A_cache_universe_2019..2026.csv'), '#B8332A', 2.2),
    ('Same rule, index members only',  bm.nav_returns(OUT/'B_point_in_time_members_2019..2026.csv'), '#1F5C8B', 2.2),
    ('SPMO (buyable momentum fund)',   bm.etf_returns('SPMO'), '#3E7A4E', 2.0),
    ('SPY',                            bm.etf_returns('SPY'), '#8A8A8A', 1.6),
]
A, B = '2019-01-01', '2026-09-17'
fig, ax = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True, gridspec_kw={'height_ratios': [2.1, 1]})
for label, s, colour, lw in SERIES:
    r = s.loc[A:B]
    w = (1 + r).cumprod()
    ax[0].plot(w.index, w, color=colour, lw=lw, label=label, solid_capstyle='round')
    ax[0].annotate(f'{w.iloc[-1]:.1f}x', (w.index[-1], w.iloc[-1]), xytext=(6, -3),
                   textcoords='offset points', color=colour, fontsize=10, fontweight='bold')
    peak = np.maximum.accumulate(w.to_numpy())
    ax[1].plot(w.index, (w.to_numpy()/peak - 1)*100, color=colour, lw=lw*0.8)
ax[0].set_yscale('log'); ax[0].set_yticks([1, 2, 4, 8, 16]); ax[0].set_yticklabels(['1x','2x','4x','8x','16x'])
ax[0].set_title('Survivorship bias is the whole of the momentum candidate\n'
                'Growth of $1, net of costs, 2019 - September 2026', fontsize=13, loc='left', pad=14)
ax[0].legend(frameon=False, loc='upper left', fontsize=10)
ax[1].set_ylabel('drawdown (%)', fontsize=10)
ax[1].axhline(0, color='#cccccc', lw=0.8)
for a in ax:
    a.grid(axis='y', color='#eeeeee', lw=0.8)
    for side in ('top', 'right'): a.spines[side].set_visible(False)
fig.text(0.011, 0.015, 'Arm B restricts the identical rule to names already in the S&P 500 on each decision date. '
         'It still cannot price the 23% of 2019 members since removed, so it remains an upper bound.',
         fontsize=8.5, color='#666666')
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(OUT/'survivorship.png', dpi=150)
print('written', OUT/'survivorship.png')
