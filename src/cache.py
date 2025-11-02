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

from enterprise_config import config

logger = logging.getLogger(__name__)


class AnalysisCache:
    """SQLite-based cache for image analysis results"""

    def __init__(self, cache_file: str = None):
        self.cache_file = cache_file or os.path.join(
            config.temp_dir, "analysis_cache.db")
        self.cache_dir = os.path.dirname(self.cache_file)

        # Ensure cache directory exists
        os.makedirs(self.cache_dir, exist_ok=True)

        # Initialize database
        self._init_database()

        logger.info(f"AnalysisCache initialized with file: {self.cache_file}")

    def _init_database(self):
        """Initialize cache database tables"""
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

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def get_analysis(self, url: str) -> Optional[Dict[str, Any]]:
        """Get cached analysis for URL"""
        url_hash = self.get_url_hash(url)

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

        return None

    def set_analysis(self, url: str, analysis: Dict[str, Any]):
        """Cache analysis result for URL"""
        url_hash = self.get_url_hash(url)
        analysis_json = json.dumps(analysis)

        with sqlite3.connect(self.cache_file) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO analysis_cache 
                (url_hash, url, analysis_data, created_at, accessed_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (url_hash, url, analysis_json))
            conn.commit()

    def batch_get_missing_urls(self, urls: List[str]) -> List[str]:
        """Get list of URLs that are not in cache"""
        if not urls:
            return []

        url_hashes = [self.get_url_hash(url) for url in urls]

        with sqlite3.connect(self.cache_file) as conn:
            # Create placeholder string for IN clause
            placeholders = ','.join('?' * len(url_hashes))

            cursor = conn.execute(
                f"SELECT url_hash FROM analysis_cache WHERE url_hash IN ({placeholders})",
                url_hashes
            )

            cached_hashes = {row[0] for row in cursor.fetchall()}

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

        return results

    def cleanup_old_entries(self, days: int = 30):
        """Remove cache entries older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days)

        with sqlite3.connect(self.cache_file) as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_cache WHERE created_at < ?",
                (cutoff_date,)
            )

            deleted_count = cursor.rowcount
            conn.commit()

        logger.info(f"Cleaned up {deleted_count} old cache entries")
        return deleted_count

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with sqlite3.connect(self.cache_file) as conn:
            # Total entries
            total_cursor = conn.execute("SELECT COUNT(*) FROM analysis_cache")
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

    def clear_cache(self):
        """Clear all cache entries"""
        with sqlite3.connect(self.cache_file) as conn:
            conn.execute("DELETE FROM analysis_cache")
            conn.commit()

        logger.info("Cache cleared")


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
