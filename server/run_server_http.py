#!/usr/bin/env python3
"""
Flask Web Server launcher script for the enterprise system.
This script handles the imports properly and starts the Flask server.
"""
import sys
import os
import argparse

# Add the parent directory to Python path (where src is located)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Enterprise Image Analyzer Server')
    parser.add_argument('--host', default='127.0.0.1',
                        help='Host to bind the server to')
    parser.add_argument('--port', type=int, default=5001,
                        help='Port to bind the server to')
    args = parser.parse_args()

    # Import and run the enterprise app
    # Note: Don't change to src directory since that breaks template path resolution
    from src.enterprise_app import enterprise_app

    print("=" * 60)
    print("🚀 Enterprise Image Analyzer Server")
    print("=" * 60)
    print(f"📍 Server URL: http://{args.host}:{args.port}")
    print(f"📊 Dashboard: http://{args.host}:{args.port}")
    print(f"🔧 Health Check: http://{args.host}:{args.port}/api/v1/health")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print()

    try:
        enterprise_app.run(
            host=args.host,
            port=args.port,
            debug=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server failed to start: {e}")
        sys.exit(1)
