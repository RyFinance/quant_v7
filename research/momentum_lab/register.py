"""Append a plan or amendment to the project pre-registration ledger. Run BEFORE any result."""
from __future__ import annotations
import hashlib, json, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / 'research/preregistrations.jsonl'


def register(rel_path: str, note: str) -> dict:
    f = ROOT / rel_path
    entry = {'file': rel_path, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest(),
             'registered_at': datetime.datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z'),
             'note': note, 'results_computed_before_registration': False}
    with open(LEDGER, 'a') as fh:
        fh.write(json.dumps(entry) + '\n')
    return entry


if __name__ == '__main__':
    print(json.dumps(register(sys.argv[1], sys.argv[2]), indent=2))
