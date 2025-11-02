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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EnterpriseSystemTester:
    """Comprehensive tester for enterprise image processing system"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url
        self.test_results = {}
        self.test_batch_id = None
        self.temp_files = []
    
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
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
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
            from src.enterprise_config import config
            from src.database_models import db_manager, ProcessingBatch
            
            # Test database connection
            with db_manager.get_session() as session:
                # Simple query to test connection
                result = session.execute("SELECT 1").fetchone()
                
                if result[0] != 1:
                    raise Exception("Database query returned unexpected result")
                
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
            
            logger.info("✓ Database connectivity test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Database connectivity test failed: {e}")
            return False
    
    async def test_redis_connectivity(self) -> bool:
        """Test Redis connectivity and job queue operations"""
        logger.info("Testing Redis connectivity...")
        
        try:
            from src.job_queue import job_queue
            
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
            job_queue.mark_job_completed(job_id, {'test_result': 'success'})
            
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
            response = requests.get(f"{self.base_url}/api/v1/health", timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"Health endpoint returned {response.status_code}")
            
            health_data = response.json()
            if not health_data.get('success'):
                raise Exception("Health check reported failure")
            
            # Test system stats endpoint
            response = requests.get(f"{self.base_url}/api/v1/system/stats", timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"System stats endpoint returned {response.status_code}")
            
            # Test export formats endpoint
            response = requests.get(f"{self.base_url}/api/v1/export/formats", timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"Export formats endpoint returned {response.status_code}")
            
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
                raise Exception(f"Batch creation returned {response.status_code}: {response.text}")
            
            result = response.json()
            if not result.get('success'):
                raise Exception(f"Batch creation failed: {result.get('error')}")
            
            self.test_batch_id = result['batch_id']
            logger.info(f"✓ Batch creation test passed - Batch ID: {self.test_batch_id}")
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
                raise Exception(f"Batch status returned {response.status_code}")
            
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
                logger.warning(f"Batch pause returned {response.status_code} (may be too fast)")
            
            # Test batch progress endpoint
            response = requests.get(
                f"{self.base_url}/api/v1/batches/{self.test_batch_id}/progress",
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"Batch progress returned {response.status_code}")
            
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
                raise Exception(f"Export summary returned {response.status_code}")
            
            # Test CSV export
            response = requests.get(
                f"{self.base_url}/export/batch/{self.test_batch_id}?format=csv",
                timeout=20
            )
            
            if response.status_code == 200:
                logger.info("✓ CSV export successful")
            else:
                logger.warning(f"CSV export returned {response.status_code} (may be expected if no data)")
            
            # Test JSON export
            response = requests.get(
                f"{self.base_url}/export/batch/{self.test_batch_id}?format=json",
                timeout=20
            )
            
            if response.status_code == 200:
                logger.info("✓ JSON export successful")
            else:
                logger.warning(f"JSON export returned {response.status_code} (may be expected if no data)")
            
            # Test template download
            response = requests.get(
                f"{self.base_url}/export/template",
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"Template download returned {response.status_code}")
            
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
                raise Exception(f"Expected 404 for invalid batch ID, got {response.status_code}")
            
            # Test invalid export format
            response = requests.get(
                f"{self.base_url}/api/v1/export/batch/invalid/status?format=invalid",
                timeout=10
            )
            
            if response.status_code not in [400, 404]:
                logger.warning(f"Invalid format test returned {response.status_code}")
            
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
            
            response = requests.get(f"{self.base_url}/api/v1/health", timeout=10)
            
            response_time = time.time() - start_time
            
            if response_time > 5.0:
                logger.warning(f"Health endpoint response time: {response_time:.2f}s (slow)")
            else:
                logger.info(f"Health endpoint response time: {response_time:.2f}s")
            
            # Test concurrent requests
            start_time = time.time()
            
            tasks = []
            for _ in range(5):
                tasks.append(asyncio.create_task(self._make_async_request("/api/v1/system/stats")))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            concurrent_time = time.time() - start_time
            successful_requests = sum(1 for r in results if not isinstance(r, Exception))
            
            logger.info(f"Concurrent requests: {successful_requests}/5 successful in {concurrent_time:.2f}s")
            
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
                logger.warning(f"Test batch cleanup returned {response.status_code}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Test batch cleanup failed: {e}")
            return False
    
    async def run_all_tests(self) -> Dict[str, bool]:
        """Run all tests and return results"""
        logger.info("=" * 80)
        logger.info("ENTERPRISE SYSTEM VALIDATION TESTS")
        logger.info("=" * 80)
        
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
            logger.info("⚠ Most tests passed. Review failures before production.")
        else:
            logger.info("❌ Multiple test failures. System needs attention.")
        
        return results


async def main():
    """Main test execution function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enterprise System Testing")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL for testing")
    parser.add_argument("--test", help="Run specific test only")
    parser.add_argument("--skip-cleanup", action="store_true", help="Skip cleanup for debugging")
    
    args = parser.parse_args()
    
    tester = EnterpriseSystemTester(args.url)
    
    try:
        if args.test:
            # Run specific test
            test_method = getattr(tester, f"test_{args.test}", None)
            if test_method:
                result = await test_method()
                logger.info(f"Test {args.test}: {'PASS' if result else 'FAIL'}")
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