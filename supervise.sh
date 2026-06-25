cd /Users/q0w01lh/Documents/repo/t2c
PID=""
for i in $(seq 1 400); do
  if grep -q "orchestrate DONE" logs/orchestrate.log 2>/dev/null; then echo "ORCHESTRATOR DONE"; break; fi
  if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "$(date '+%H:%M:%S') (re)launching orchestrator"
    nohup python orchestrate_cyanchor.py >> logs/orchestrate.nohup 2>&1 &
    PID=$!
    echo "  orchestrator pid=$PID"
  fi
  sleep 120
done
