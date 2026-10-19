"""Local preview; deliberately bound to loopback."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    print('Ggolde Lab: http://127.0.0.1:8090',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8090),partial(SimpleHTTPRequestHandler,directory=str(ROOT/'site'))).serve_forever()
