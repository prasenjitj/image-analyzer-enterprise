#!/usr/bin/env python3
"""
Flask Web Server launcher script for the enterprise system.
This script handles the imports properly and starts the Flask server.
"""
import sys
import os

# Add the parent directory to Python path (where src is located)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

if __name__ == '__main__':
    # Import and run the enterprise app
    # Note: Don't change to src directory since that breaks template path resolution
    from src.enterprise_app import enterprise_app

    print("=" * 60)
    print("🚀 Enterprise Image Analyzer Server")
    print("=" * 60)
    print("📍 Server URL: http://127.0.0.1:5001")
    print("📊 Dashboard: http://127.0.0.1:5001")
    print("🔧 Health Check: http://127.0.0.1:5001/api/v1/health")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print()

    try:
        enterprise_app.run(
            host='127.0.0.1',
            port=5001,
            debug=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Server failed to start: {e}")
        sys.exit(1)
