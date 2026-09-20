#!/bin/zsh
# One queue for the two option pulls and their registered development runs, in order:
# SPY/QQQ/IWM put writing first (about 2 hours), then the remaining stock-option names (about 16 hours).
cd /Users/rytty/CCP/quant_v7
mkdir -p reports/putwrite reports/options_signals
PYTHONPATH=. .venv/bin/python -m research.putwrite.pull >> reports/putwrite/pull.log 2>&1
if [ -f data/lse/options_etf_1d/QQQ.parquet ] && [ -f data/lse/options_etf_1d/IWM.parquet ]; then
  PYTHONPATH=. .venv/bin/python -m research.putwrite.evaluate dev > reports/putwrite/dev_run.log 2>&1
  echo "exit=$? $(date)" >> reports/putwrite/dev_run.log
fi
PYTHONPATH=. .venv/bin/python -m data.pull_options_1d >> data/lse/options_1d/pull.log 2>&1
PYTHONPATH=. .venv/bin/python -m research.options_signals.evaluate dev > reports/options_signals/dev_run.log 2>&1
echo "exit=$? $(date)" >> reports/options_signals/dev_run.log
