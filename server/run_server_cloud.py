#!/usr/bin/env python3
"""
Container-friendly server launcher for Enterprise Image Analyzer.

Use this in Docker/Cloud Run. It binds to 0.0.0.0 and reads PORT from the
environment (default 8080) so the platform can health-check and route traffic.

Keep run_server.py for local development.
"""
import os
import sys

# Ensure project root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)  # Go up to project root
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from src.enterprise_app import enterprise_app  # noqa: E402


def main():
    host = '0.0.0.0'
    port = int(os.environ.get('PORT', '8080'))
    enterprise_app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
