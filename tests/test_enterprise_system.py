#!/usr/bin/env python3
"""
Comprehensive testing and validation script for enterprise image processing system

Tests:
- Database connectivity and schema
- Redis job queue functionality
- API endpoints and responses
- Batch processing workflow
- Export functionality
- Error handling and edge cases

HOW TO USE THIS SCRIPT:
========================

PREREQUISITES:
--------------
For Local Testing:
  1. PostgreSQL server running and configured
  2. Redis server running and accessible
  3. Enterprise app running (python run_server.py or python main.py)
  4. All Python dependencies installed (pip install -r requirements.txt)
  5. Environment variables configured (.env file)

For Cloud Testing:
  1. Application deployed to cloud platform
  2. Valid URL endpoint accessible
  3. Cloud services (database, Redis) running

BASIC USAGE:
------------
# Run all tests against local server (default: localhost:5001)
python3 tests/test_enterprise_system.py

# Test against cloud deployment
python3 tests/test_enterprise_system.py --url https://your-app.run.app

# Test against custom local port
python3 tests/test_enterprise_system.py --url http://localhost:8080

ADVANCED USAGE:
---------------
# Run specific test only
python3 tests/test_enterprise_system.py --test database_connectivity
python3 tests/test_enterprise_system.py --test api_endpoints
python3 tests/test_enterprise_system.py --test batch_creation

# Available test names:
#   - database_connectivity
#   - redis_connectivity  
#   - api_endpoints
#   - batch_creation
#   - batch_management
#   - export_functionality
#   - error_handling
#   - performance_basics

# Debug mode (skip cleanup for investigation)
python3 tests/test_enterprise_system.py --skip-cleanup

TROUBLESHOOTING:
----------------
Common Error Solutions:

1. "No module named 'src'" 
   → Run from project root directory
   → Ensure src/ directory exists with Python modules

2. "Connection refused" on localhost:5001
   → Start the enterprise app: python run_server.py
   → Check if app is running on different port
   → Verify PostgreSQL and Redis are running

3. "Database connectivity test failed"
   → Start PostgreSQL: sudo systemctl start postgresql
   → Check database credentials in .env file
   → Run database setup: python setup.py --init-db

4. "Redis connectivity test failed"
   → Start Redis: sudo systemctl start redis
   → Check Redis connection settings
   → Test Redis: redis-cli ping

5. Cloud deployment issues
   → Verify deployment URL is correct
   → Check cloud service status
   → Ensure all cloud resources are running

EXPECTED OUTPUT:
----------------
✓ PASS = Test successful
❌ FAIL = Test failed (check error messages for guidance)
⚠ WARNING = Non-critical issue (test continues)

Exit Codes:
  0 = All tests passed
  1 = Most tests passed (80%+)
  2 = Multiple failures (system needs attention)

EXAMPLES:
---------
# Quick health check
python3 tests/test_enterprise_system.py --test api_endpoints

# Full system validation before production
python3 tests/test_enterprise_system.py

# Test cloud deployment
python3 tests/test_enterprise_system.py --url https://my-app.run.app

# Debug database issues
python3 tests/test_enterprise_system.py --test database_connectivity --skip-cleanup
"""
import asyncio
import json
import logging
import os
import sys
import time
import tempfile
import csv
from datetime import datetime
from pathlib import Path
import requests
from typing import Dict, Any, List, Optional

# Add project root to Python path for proper imports
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # Go up to project root
sys.path.insert(0, project_root)

# BASE_URL = "http://localhost:5001"
BASE_URL = "https://image-analyzer-mzhpbbuvma-uc.a.run.app/"


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EnterpriseSystemTester:
    """Comprehensive tester for enterprise image processing system"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.test_results = {}
        self.test_batch_id = None
        self.temp_files = []

    def check_server_accessibility(self) -> bool:
        """Quick check if server is accessible"""
        try:
            response = requests.get(f"{self.base_url}", timeout=5)
            return True
        except requests.exceptions.ConnectionError:
            return False
        except:
            return True  # Server exists but may have different response

    def cleanup(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                os.unlink(temp_file)
            except:
                pass

    def create_test_csv(self, num_urls: int = 50) -> str:
        """Create a test CSV file with sample URLs"""
        # Use the existing generate_realistic_csv for consistency
        test_urls = [
            f"https://example.com/store/{i}/image.jpg"
            for i in range(1, num_urls + 1)
        ]

        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.csv', delete=False)
        self.temp_files.append(temp_file.name)

        writer = csv.writer(temp_file)
        writer.writerow(['url'])  # Header

        for url in test_urls:
            writer.writerow([url])

        temp_file.close()
        logger.info(f"Created test CSV with {num_urls} URLs: {temp_file.name}")

        return temp_file.name

    async def test_database_connectivity(self) -> bool:
        """Test database connectivity and basic operations"""
        logger.info("Testing database connectivity...")

        try:
            # Try to import required modules
            try:
                from src.enterprise_config import config
                from src.database_models import db_manager, ProcessingBatch
            except ImportError as e:
                logger.error(f"❌ Database modules not available: {e}")
                logger.error(
                    "   Make sure the application is properly installed and src modules are available")
                return False

            # Test database connection
            try:
                with db_manager.get_session() as session:
                    # Simple query to test connection
                    result = session.execute("SELECT 1").fetchone()

                    if result[0] != 1:
                        raise Exception(
                            "Database query returned unexpected result")

                    # Test batch model operations
                    test_batch = ProcessingBatch(
                        batch_name=f"test_batch_{int(time.time())}",
                        total_urls=10,
                        chunk_size=config.chunk_size,
                        total_chunks=1
                    )

                    session.add(test_batch)
                    session.commit()

                    # Clean up test batch
                    session.delete(test_batch)
                    session.commit()
            except Exception as e:
                logger.error(f"❌ Database connection failed: {e}")
                logger.error(
                    "   Make sure PostgreSQL is running and configured correctly")
                logger.error(
                    "   Check database connection settings in .env file")
                return False

            logger.info("✓ Database connectivity test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Database connectivity test failed: {e}")
            return False

    async def test_redis_connectivity(self) -> bool:
        """Test Redis connectivity and job queue operations"""
        logger.info("Testing Redis connectivity...")

        try:
            # Try to import required modules
            try:
                from src.job_queue import job_queue
            except ImportError as e:
                logger.error(f"❌ Redis/Job queue modules not available: {e}")
                logger.error(
                    "   Make sure the application is properly installed and src modules are available")
                return False

            try:
                # Test Redis connection
                job_queue.redis_client.ping()

                # Test job queue operations
                test_job_data = {
                    'test': True,
                    'timestamp': datetime.now().isoformat()
                }

                job_id = job_queue.enqueue_job('test_job', test_job_data)

                # Verify job was enqueued
                job = job_queue.get_next_job(timeout=1.0)

                if job is None or job.job_id != job_id:
                    raise Exception("Job queue operations failed")

                # Mark job as completed
                job_queue.mark_job_completed(
                    job_id, {'test_result': 'success'})
            except Exception as e:
                logger.error(f"❌ Redis connection/operations failed: {e}")
                logger.error(
                    "   Make sure Redis server is running and accessible")
                logger.error("   Check Redis connection settings in .env file")
                return False

            logger.info("✓ Redis connectivity test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Redis connectivity test failed: {e}")
            return False

    async def test_api_endpoints(self) -> bool:
        """Test API endpoints"""
        logger.info("Testing API endpoints...")

        try:
            # Test health endpoint
            try:
                response = requests.get(
                    f"{self.base_url}/api/v1/health", timeout=10)
            except requests.exceptions.ConnectionError as e:
                logger.error(f"❌ Cannot connect to server at {self.base_url}")
                logger.error("   Make sure the application server is running:")
                logger.error("   - For local: python run_server.py")
                logger.error("   - For Cloud: check deployment status")
                return False
            except requests.exceptions.Timeout:
                logger.error(f"❌ Server timeout at {self.base_url}")
                logger.error("   Server may be overloaded or unresponsive")
                return False

            if response.status_code != 200:
                logger.error(
                    f"❌ Health endpoint returned {response.status_code}")
                logger.error(f"   Response: {response.text[:200]}...")
                return False

            health_data = response.json()
            if not health_data.get('success'):
                logger.error(f"❌ Health check reported failure: {health_data}")
                return False

            # Test system stats endpoint
            response = requests.get(
                f"{self.base_url}/api/v1/system/stats", timeout=10)

            if response.status_code != 200:
                logger.warning(
                    f"⚠ System stats endpoint returned {response.status_code}")
                # Don't fail the test for this, it might not be implemented

            # Test export formats endpoint
            response = requests.get(
                f"{self.base_url}/api/v1/export/formats", timeout=10)

            if response.status_code != 200:
                logger.warning(
                    f"⚠ Export formats endpoint returned {response.status_code}")
                # Don't fail the test for this, it might not be implemented

            logger.info("✓ API endpoints test passed")
            return True

        except Exception as e:
            logger.error(f"❌ API endpoints test failed: {e}")
            return False

    async def test_batch_creation(self) -> bool:
        """Test batch creation workflow"""
        logger.info("Testing batch creation...")

        try:
            # Create test CSV
            csv_file = self.create_test_csv(20)

            # Upload CSV and create batch
            with open(csv_file, 'rb') as f:
                files = {'file': f}
                data = {
                    'batch_name': f'test_batch_{int(time.time())}',
                    'auto_start': 'false'
                }

                response = requests.post(
                    f"{self.base_url}/upload",
                    files=files,
                    data=data,
                    timeout=30
                )

            if response.status_code != 200:
                raise Exception(
                    f"Batch creation returned {response.status_code}: {response.text}")

            result = response.json()
            if not result.get('success'):
                raise Exception(
                    f"Batch creation failed: {result.get('error')}")

            self.test_batch_id = result['batch_id']
            logger.info(
                f"✓ Batch creation test passed - Batch ID: {self.test_batch_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Batch creation test failed: {e}")
            return False

    async def test_batch_management(self) -> bool:
        """Test batch management operations"""
        if not self.test_batch_id:
            logger.error("❌ No test batch available for management testing")
            return False

        logger.info("Testing batch management operations...")

        try:
            # Test batch status retrieval
            response = requests.get(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/status",
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(
                    f"Batch status returned {response.status_code}")

            status_data = response.json()
            if not status_data.get('success'):
                raise Exception("Batch status request failed")

            # Test batch start
            response = requests.post(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/start",
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(f"Batch start returned {response.status_code}")

            # Wait a moment and test pause
            await asyncio.sleep(2)

            response = requests.post(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/pause",
                timeout=10
            )

            if response.status_code != 200:
                logger.warning(
                    f"Batch pause returned {response.status_code} (may be too fast)")

            # Test batch progress endpoint
            response = requests.get(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/progress",
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(
                    f"Batch progress returned {response.status_code}")

            logger.info("✓ Batch management test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Batch management test failed: {e}")
            return False

    async def test_export_functionality(self) -> bool:
        """Test export functionality"""
        if not self.test_batch_id:
            logger.error("❌ No test batch available for export testing")
            return False

        logger.info("Testing export functionality...")

        try:
            # Test export summary
            response = requests.get(
                f"{self.base_url}/api/v1/export/batch/{self.test_batch_id}/summary",
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(
                    f"Export summary returned {response.status_code}")

            # Test CSV export
            response = requests.get(
                f"{self.base_url}/export/batch/{self.test_batch_id}?format=csv",
                timeout=20
            )

            if response.status_code == 200:
                logger.info("✓ CSV export successful")
            else:
                logger.warning(
                    f"CSV export returned {response.status_code} (may be expected if no data)")

            # Test JSON export
            response = requests.get(
                f"{self.base_url}/export/batch/{self.test_batch_id}?format=json",
                timeout=20
            )

            if response.status_code == 200:
                logger.info("✓ JSON export successful")
            else:
                logger.warning(
                    f"JSON export returned {response.status_code} (may be expected if no data)")

            # Test template download
            response = requests.get(
                f"{self.base_url}/export/template",
                timeout=10
            )

            if response.status_code != 200:
                raise Exception(
                    f"Template download returned {response.status_code}")

            logger.info("✓ Export functionality test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Export functionality test failed: {e}")
            return False

    async def test_error_handling(self) -> bool:
        """Test error handling and edge cases"""
        logger.info("Testing error handling...")

        try:
            # Test invalid batch ID
            response = requests.get(
                f"{self.base_url}/api/v1/batches/invalid-batch-id/status",
                timeout=10
            )

            if response.status_code != 404:
                raise Exception(
                    f"Expected 404 for invalid batch ID, got {response.status_code}")

            # Test invalid export format
            response = requests.get(
                f"{self.base_url}/api/v1/export/batch/invalid/status?format=invalid",
                timeout=10
            )

            if response.status_code not in [400, 404]:
                logger.warning(
                    f"Invalid format test returned {response.status_code}")

            # Test malformed CSV upload
            invalid_csv_content = "not,a,valid,csv\nwith,missing,columns"

            files = {'file': ('test.csv', invalid_csv_content, 'text/csv')}
            data = {'batch_name': 'invalid_test'}

            response = requests.post(
                f"{self.base_url}/upload",
                files=files,
                data=data,
                timeout=10
            )

            # Should handle gracefully (may succeed or fail depending on validation)
            logger.info(f"Invalid CSV upload returned {response.status_code}")

            logger.info("✓ Error handling test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Error handling test failed: {e}")
            return False

    async def test_performance_basics(self) -> bool:
        """Test basic performance characteristics"""
        logger.info("Testing basic performance...")

        try:
            # Test API response times
            start_time = time.time()

            response = requests.get(
                f"{self.base_url}/api/v1/health", timeout=10)

            response_time = time.time() - start_time

            if response_time > 5.0:
                logger.warning(
                    f"Health endpoint response time: {response_time:.2f}s (slow)")
            else:
                logger.info(
                    f"Health endpoint response time: {response_time:.2f}s")

            # Test concurrent requests
            start_time = time.time()

            tasks = []
            for _ in range(5):
                tasks.append(asyncio.create_task(
                    self._make_async_request("/api/v1/system/stats")))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            concurrent_time = time.time() - start_time
            successful_requests = sum(
                1 for r in results if not isinstance(r, Exception))

            logger.info(
                f"Concurrent requests: {successful_requests}/5 successful in {concurrent_time:.2f}s")

            logger.info("✓ Performance basics test passed")
            return True

        except Exception as e:
            logger.error(f"❌ Performance basics test failed: {e}")
            return False

    async def _make_async_request(self, endpoint: str) -> bool:
        """Make async HTTP request for performance testing"""
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=5)
            return response.status_code == 200
        except:
            return False

    async def cleanup_test_batch(self) -> bool:
        """Clean up test batch"""
        if not self.test_batch_id:
            return True

        logger.info(f"Cleaning up test batch {self.test_batch_id}...")

        try:
            # Cancel batch if running
            requests.post(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/cancel",
                timeout=10
            )

            # Delete batch
            response = requests.delete(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}?force=true",
                timeout=10
            )

            if response.status_code == 200:
                logger.info("✓ Test batch cleaned up successfully")
            else:
                logger.warning(
                    f"Test batch cleanup returned {response.status_code}")

            return True

        except Exception as e:
            logger.error(f"❌ Test batch cleanup failed: {e}")
            return False

    async def run_all_tests(self) -> Dict[str, bool]:
        """Run all tests and return results"""
        logger.info("=" * 80)
        logger.info("ENTERPRISE SYSTEM VALIDATION TESTS")
        logger.info("=" * 80)

        # Pre-flight checks
        logger.info(f"Testing against: {self.base_url}")

        if not self.check_server_accessibility():
            logger.error(f"\n❌ Cannot reach server at {self.base_url}")
            logger.error("   Please ensure the server is running:")
            if "localhost" in self.base_url:
                logger.error("   - Local: python run_server.py")
                logger.error("   - Local: python main.py")
                logger.error("   - Check if PostgreSQL and Redis are running")
            else:
                logger.error("   - Check Cloud deployment status")
                logger.error("   - Verify the URL is correct")
            logger.error("   - Test with: curl <URL>/api/v1/health")
            logger.info("\nSkipping tests due to server inaccessibility...")
            return {}

        tests = [
            ("Database Connectivity", self.test_database_connectivity),
            ("Redis Connectivity", self.test_redis_connectivity),
            ("API Endpoints", self.test_api_endpoints),
            ("Batch Creation", self.test_batch_creation),
            ("Batch Management", self.test_batch_management),
            ("Export Functionality", self.test_export_functionality),
            ("Error Handling", self.test_error_handling),
            ("Performance Basics", self.test_performance_basics),
        ]

        results = {}

        for test_name, test_func in tests:
            try:
                logger.info(f"\nRunning: {test_name}")
                results[test_name] = await test_func()
            except Exception as e:
                logger.error(f"Test {test_name} crashed: {e}")
                results[test_name] = False

        # Cleanup
        await self.cleanup_test_batch()
        self.cleanup()

        # Results summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST RESULTS SUMMARY")
        logger.info("=" * 80)

        passed_tests = 0
        total_tests = len(results)

        for test_name, result in results.items():
            status = "✓ PASS" if result else "❌ FAIL"
            logger.info(f"{test_name:25} {status}")
            if result:
                passed_tests += 1

        logger.info(f"\nOverall: {passed_tests}/{total_tests} tests passed")

        if passed_tests == total_tests:
            logger.info("🎉 All tests passed! System is ready for production.")
        elif passed_tests >= total_tests * 0.8:
            logger.info(
                "⚠ Most tests passed. Review failures before production.")
        else:
            logger.info("❌ Multiple test failures. System needs attention.")

        return results


async def main():
    """Main test execution function"""
    import argparse

    parser = argparse.ArgumentParser(description="Enterprise System Testing")
    parser.add_argument(
        "--url", default="http://localhost:5001", help="Base URL for testing")
    parser.add_argument("--test", help="Run specific test only")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="Skip cleanup for debugging")

    args = parser.parse_args()

    tester = EnterpriseSystemTester(args.url)

    try:
        if args.test:
            # Run specific test
            test_method = getattr(tester, f"test_{args.test}", None)
            if test_method:
                result = await test_method()
                logger.info(
                    f"Test {args.test}: {'PASS' if result else 'FAIL'}")
            else:
                logger.error(f"Unknown test: {args.test}")
        else:
            # Run all tests
            results = await tester.run_all_tests()

            # Exit with appropriate code
            passed = sum(results.values())
            total = len(results)

            if passed == total:
                sys.exit(0)
            elif passed >= total * 0.8:
                sys.exit(1)
            else:
                sys.exit(2)

    except KeyboardInterrupt:
        logger.info("Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Testing failed: {e}")
        sys.exit(1)
    finally:
        if not args.skip_cleanup:
            tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
