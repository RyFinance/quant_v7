#!/bin/zsh
# Waits until all 100 universe option files exist and neither the option pull, its queue script nor the
# registered options-signals evaluation is running; then runs the IV-change development evaluation once.
# Gives up after 72 hours.
cd /Users/rytty/CCP/quant_v7
LOG=reports/iv_changes/waiter.log
mkdir -p reports/iv_changes
echo "waiter start $(date) pid=$$" >> $LOG
deadline=$(( $(date +%s) + 72*3600 ))
while true; do
  n=$(.venv/bin/python -c "import json,os;u=json.load(open('data/lse/options_1d/universe.json'))['names'];print(sum(os.path.exists(f'data/lse/options_1d/{t}.parquet') for t in u))")
  busy=0
  pgrep -f "research.options_signals.evaluate" >/dev/null && busy=1
  pgrep -f "data.pull_options_1d" >/dev/null && busy=1
  pgrep -f "run_pending_pulls.sh" >/dev/null && busy=1
  if [ "$n" = "100" ] && [ $busy = 0 ]; then break; fi
  if [ $(date +%s) -gt $deadline ]; then echo "gave up $(date): files=$n busy=$busy" >> $LOG; exit 1; fi
  echo "$(date +%H:%M) files=$n busy=$busy" >> $LOG
  sleep 600
done
if [ -f reports/iv_changes/dev/results.json ]; then echo "dev already ran; not rerunning" >> $LOG; exit 0; fi
echo "starting dev $(date)" >> $LOG
PYTHONPATH=. .venv/bin/python -m research.iv_changes.evaluate dev > reports/iv_changes/dev_run.log 2>&1
echo "exit=$? $(date)" >> reports/iv_changes/dev_run.log
echo "done $(date)" >> $LOG
