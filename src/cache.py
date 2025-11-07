"""
Caching system for image analysis results
"""
import sqlite3
import json
import logging
import hashlib
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path

from .enterprise_config import config

logger = logging.getLogger(__name__)


class AnalysisCache:
    """SQLite-based cache for image analysis results"""

    def __init__(self, cache_file: str = None):
        # Use absolute path to ensure consistency across processes
        if cache_file:
            self.cache_file = os.path.abspath(cache_file)
        else:
            # Get the project root directory
            project_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
            temp_dir = os.path.join(project_root, "temp")
            os.makedirs(temp_dir, exist_ok=True)
            self.cache_file = os.path.join(temp_dir, "analysis_cache.db")

        self.cache_dir = os.path.dirname(self.cache_file)

        # Ensure cache directory exists
        os.makedirs(self.cache_dir, exist_ok=True)

        # Initialize database
        self._init_database()

        logger.info(f"AnalysisCache initialized with file: {self.cache_file}")

    def _init_database(self):
        """Initialize cache database tables"""
        try:
            with sqlite3.connect(self.cache_file) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS analysis_cache (
                        url_hash TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        analysis_data TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        access_count INTEGER DEFAULT 1
                    )
                """)

                # Create index for faster lookups
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_created_at ON analysis_cache(created_at)
                """)

                conn.commit()
                logger.debug(
                    f"Cache database initialized successfully at {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to initialize cache database: {e}")
            raise

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL (non-security use)"""
        return hashlib.md5(url.encode('utf-8'), usedforsecurity=False).hexdigest()

    def get_analysis(self, url: str) -> Optional[Dict[str, Any]]:
        """Get cached analysis for URL"""
        url_hash = self.get_url_hash(url)

        try:
            with sqlite3.connect(self.cache_file) as conn:
                cursor = conn.execute(
                    "SELECT analysis_data FROM analysis_cache WHERE url_hash = ?",
                    (url_hash,)
                )

                row = cursor.fetchone()
                if row:
                    # Update access statistics
                    conn.execute("""
                        UPDATE analysis_cache 
                        SET accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1
                        WHERE url_hash = ?
                    """, (url_hash,))
                    conn.commit()

                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Invalid cached data for URL hash {url_hash}")
                        return None

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, skipping cache read: {e}")
                return None
            else:
                logger.error(f"Cache database error: {e}")
                return None
        except Exception as e:
            logger.error(f"Unexpected cache error: {e}")
            return None

        return None

    def set_analysis(self, url: str, analysis: Dict[str, Any]):
        """Cache analysis result for URL"""
        url_hash = self.get_url_hash(url)
        analysis_json = json.dumps(analysis)

        try:
            with sqlite3.connect(self.cache_file) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO analysis_cache 
                    (url_hash, url, analysis_data, created_at, accessed_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (url_hash, url, analysis_json))
                conn.commit()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, initializing and retrying: {e}")
                self._init_database()
                try:
                    with sqlite3.connect(self.cache_file) as conn:
                        conn.execute("""
                            INSERT OR REPLACE INTO analysis_cache 
                            (url_hash, url, analysis_data, created_at, accessed_at)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """, (url_hash, url, analysis_json))
                        conn.commit()
                except Exception as e2:
                    logger.error(
                        f"Failed to store analysis after table recreation: {e2}")
            else:
                logger.error(f"Cache database error: {e}")
        except Exception as e:
            logger.error(f"Unexpected cache error: {e}")

    def batch_get_missing_urls(self, urls: List[str]) -> List[str]:
        """Get list of URLs that are not in cache"""
        if not urls:
            return []

        url_hashes = [self.get_url_hash(url) for url in urls]

        try:
            with sqlite3.connect(self.cache_file) as conn:
                # Create placeholder string for IN clause
                placeholders = ','.join('?' * len(url_hashes))

                cursor = conn.execute(
                    f"SELECT url_hash FROM analysis_cache WHERE url_hash IN ({placeholders})",
                    url_hashes
                )

                cached_hashes = {row[0] for row in cursor.fetchall()}

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(f"Cache table does not exist, recreating: {e}")
                self._init_database()
                return urls  # Return all URLs as missing since cache is empty
            else:
                logger.error(f"Cache database error: {e}")
                return urls  # Return all URLs as missing on error
        except Exception as e:
            logger.error(f"Unexpected cache error: {e}")
            return urls  # Return all URLs as missing on error

        # Return URLs that are not cached
        missing_urls = []
        for url in urls:
            if self.get_url_hash(url) not in cached_hashes:
                missing_urls.append(url)

        return missing_urls

    def batch_get_analyses(self, urls: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get multiple cached analyses"""
        if not urls:
            return {}

        url_hashes = [self.get_url_hash(url) for url in urls]
        url_hash_to_url = {self.get_url_hash(url): url for url in urls}

        results = {}

        try:
            with sqlite3.connect(self.cache_file) as conn:
                placeholders = ','.join('?' * len(url_hashes))

                cursor = conn.execute(
                    f"""SELECT url_hash, analysis_data FROM analysis_cache 
                        WHERE url_hash IN ({placeholders})""",
                    url_hashes
                )

                for url_hash, analysis_data in cursor.fetchall():
                    try:
                        url = url_hash_to_url[url_hash]
                        analysis = json.loads(analysis_data)
                        results[url] = analysis
                    except (json.JSONDecodeError, KeyError):
                        continue

                # Update access statistics for found items
                if results:
                    found_hashes = [self.get_url_hash(
                        url) for url in results.keys()]
                    placeholders = ','.join('?' * len(found_hashes))
                    conn.execute(f"""
                        UPDATE analysis_cache 
                        SET accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1
                        WHERE url_hash IN ({placeholders})
                    """, found_hashes)
                    conn.commit()

        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, skipping cache read: {e}")
                return {}
            else:
                logger.error(f"Cache database error: {e}")
                return {}
        except Exception as e:
            logger.error(f"Unexpected cache error: {e}")
            return {}

        return results

    def cleanup_old_entries(self, days: int = 30):
        """Remove cache entries older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days)

        try:
            with sqlite3.connect(self.cache_file) as conn:
                cursor = conn.execute(
                    "DELETE FROM analysis_cache WHERE created_at < ?",
                    (cutoff_date,)
                )

                deleted_count = cursor.rowcount
                conn.commit()

            logger.info(f"Cleaned up {deleted_count} old cache entries")
            return deleted_count
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, skipping cleanup: {e}")
                return 0
            else:
                logger.error(f"Cache database error during cleanup: {e}")
                return 0
        except Exception as e:
            logger.error(f"Unexpected cache error during cleanup: {e}")
            return 0

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            with sqlite3.connect(self.cache_file) as conn:
                # Total entries
                total_cursor = conn.execute(
                    "SELECT COUNT(*) FROM analysis_cache")
                total_entries = total_cursor.fetchone()[0]

                # Cache size (approximate)
                cache_size = os.path.getsize(
                    self.cache_file) if os.path.exists(self.cache_file) else 0

                # Recent activity (last 24 hours)
                recent_cursor = conn.execute("""
                    SELECT COUNT(*) FROM analysis_cache 
                    WHERE accessed_at >= datetime('now', '-1 day')
                """)
                recent_access = recent_cursor.fetchone()[0]

                # Top accessed
                top_cursor = conn.execute("""
                    SELECT url, access_count FROM analysis_cache 
                    ORDER BY access_count DESC LIMIT 5
                """)
                top_accessed = top_cursor.fetchall()

            return {
                'total_entries': total_entries,
                'cache_size_bytes': cache_size,
                'recent_access_24h': recent_access,
                'top_accessed': top_accessed,
                'cache_file': self.cache_file
            }
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, returning empty stats: {e}")
                return {
                    'total_entries': 0,
                    'cache_size_bytes': os.path.getsize(self.cache_file) if os.path.exists(self.cache_file) else 0,
                    'recent_access_24h': 0,
                    'top_accessed': [],
                    'cache_file': self.cache_file
                }
            else:
                logger.error(f"Cache database error getting stats: {e}")
                return {
                    'total_entries': 0,
                    'cache_size_bytes': 0,
                    'recent_access_24h': 0,
                    'top_accessed': [],
                    'cache_file': self.cache_file
                }
        except Exception as e:
            logger.error(f"Unexpected cache error getting stats: {e}")
            return {
                'total_entries': 0,
                'cache_size_bytes': 0,
                'recent_access_24h': 0,
                'top_accessed': [],
                'cache_file': self.cache_file
            }

    def clear_cache(self):
        """Clear all cache entries"""
        try:
            with sqlite3.connect(self.cache_file) as conn:
                conn.execute("DELETE FROM analysis_cache")
                conn.commit()

            logger.info("Cache cleared")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                logger.warning(
                    f"Cache table does not exist, nothing to clear: {e}")
            else:
                logger.error(f"Cache database error during clear: {e}")
        except Exception as e:
            logger.error(f"Unexpected cache error during clear: {e}")


# Global cache instance
_cache_instance = None


def get_cache(cache_file: str = None) -> AnalysisCache:
    """Get global cache instance"""
    global _cache_instance

    if _cache_instance is None:
        _cache_instance = AnalysisCache(cache_file)

    return _cache_instance


def clear_global_cache():
    """Clear and reset global cache instance"""
    global _cache_instance

    if _cache_instance:
        _cache_instance.clear_cache()
        _cache_instance = None
