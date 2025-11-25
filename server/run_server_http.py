#!/usr/bin/env python3
"""
Flask Web Server launcher script for the enterprise system.
This script handles the imports properly and starts the Flask server.
"""
import sys
import os
import argparse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the parent directory to Python path (where src is located)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

if __name__ == '__main__':
    # Get defaults from environment variables
    default_host = os.getenv('SERVER_HOST', '0.0.0.0')
    default_port = int(os.getenv('SERVER_PORT', '5001'))

    parser = argparse.ArgumentParser(
        description='Enterprise Image Analyzer Server')
    parser.add_argument('--host', default=default_host,
                        help='Host to bind the server to')
    parser.add_argument('--port', type=int, default=default_port,
                        help='Port to bind the server to')
    args = parser.parse_args()

    # Import and run the enterprise app
    # Note: Don't change to src directory since that breaks template path resolution
    from src.enterprise_app import enterprise_app
    from src.enterprise_config import config

    print("=" * 60)
    print("🚀 Enterprise Image Analyzer Server")
    print("=" * 60)
    print(f"📍 Server URL: http://{args.host}:{args.port}")
    print(f"📊 Dashboard: http://{args.host}:{args.port}")
    print(f"🔧 Health Check: http://{args.host}:{args.port}/api/v1/health")
    print("=" * 60)
    print()
    print("📋 Configuration:")
    print("-" * 60)
    print(f"  DATABASE_URL:          {config.database_url[:50]}..." if len(config.database_url) > 50 else f"  DATABASE_URL:          {config.database_url}")
    print(f"  REDIS_URL:             {config.redis_url}")
    print(f"  API_ENDPOINT_URL:      {config.api_endpoint_url}")
    print(f"  MAX_CONCURRENT_WORKERS:{config.max_concurrent_workers}")
    print(f"  REQUEST_TIMEOUT:       {config.request_timeout}s")
    print(f"  CHUNK_SIZE:            {config.chunk_size}")
    print(f"  DEVELOPMENT_MODE:      {config.development_mode}")
    print(f"  DEBUG_LOGGING:         {config.enable_debug_logging}")
    print("-" * 60)
    print()
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
