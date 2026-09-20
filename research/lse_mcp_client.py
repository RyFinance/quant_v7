"""Read/research-only bridge to the user's configured LSE Terminal stdio MCP.

No trade, algo, account mutation, or workspace-write tool is permitted here.
Credentials stay in the user's existing server configuration and process.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import time

ALLOWED = {'terminal_status', 'search_instruments', 'get_quotes', 'get_history',
           'screener', 'options_chain', 'options_flow', 'news', 'macro_search',
           'macro_series', 'api_get', 'run_backtest', 'run_montecarlo', 'run_walkforward',
           'get_economics', 'list_datasets', 'list_ml_models', 'generate_ml_blueprint',
           'get_ml_job', 'list_research', 'read_research_paper', 'read_guide',
           'list_workspace', 'read_workspace_file'}


class Terminal:
    def __init__(self):
        cfg = json.loads((Path.home()/'.claude.json').read_text())['mcpServers']['lse-terminal']
        self.process = subprocess.Popen([cfg['command'], *cfg.get('args', [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, **cfg.get('env', {})})
        self.buffer = b''
        self.id = 0
        self.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
             'clientInfo': {'name': 'quant-v7-edge-research', 'version': '1'}}, 30)
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def send(self, obj):
        self.process.stdin.write((json.dumps(obj)+'\n').encode())
        self.process.stdin.flush()

    def request(self, method, params, timeout):
        self.id += 1
        self.send({'jsonrpc': '2.0', 'id': self.id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\n', 1)
                try:
                    item = json.loads(raw)
                except ValueError:
                    continue
                if item.get('id') != self.id:
                    continue
                if 'error' in item:
                    raise RuntimeError(str(item['error']))
                return item['result']
            if select.select([self.process.stdout], [], [], min(1, max(0, deadline-time.monotonic())))[0]:
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError('LSE MCP process exited')
                self.buffer += data
        raise TimeoutError(f'LSE MCP {method} timed out')

    def call(self, name, arguments=None, timeout=120):
        if name not in ALLOWED:
            raise ValueError('tool not allowed by research-only bridge')
        return self.request('tools/call', {'name': name, 'arguments': arguments or {}}, timeout)

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def content_text(result):
    return '\n'.join(x.get('text', '') for x in result.get('content', []) if x.get('type') == 'text')
