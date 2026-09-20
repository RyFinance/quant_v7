#!/bin/zsh
cd /Users/rytty/CCP/quant_v7
PYTHONPATH=. .venv/bin/python -m data.pull_options_1d >> data/lse/options_1d/pull.log 2>&1
PYTHONPATH=. .venv/bin/python -m research.options_signals.evaluate dev > reports/options_signals/dev_run.log 2>&1
echo "exit=$? $(date)" >> reports/options_signals/dev_run.log
