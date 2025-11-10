"""
Image processing module using API endpoint for enterprise batch processing
"""
import asyncio
import aiohttp
import logging
import time
import hashlib
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import json

from .enterprise_config import config

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of image processing"""
    url: str
    success: bool
    analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    cache_hit: bool = False
    phone_number: bool = False


class ImageProcessor:
    """Enterprise image processor using API endpoint"""

    def __init__(self, api_keys: List[str] = None, max_workers: int = 10):
        self.api_keys = api_keys or config.api_keys_list
        self.max_workers = max_workers
        self.current_api_key_index = 0
        self.session: Optional[aiohttp.ClientSession] = None

        logger.info(
            f"ImageProcessor initialized with API endpoint processing")

    def start_processing(self):
        """Initialize processing session"""
        if not self.session:
            connector = aiohttp.TCPConnector(limit=self.max_workers)
            timeout = aiohttp.ClientTimeout(total=config.request_timeout)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )

    async def stop_processing(self):
        """Clean up processing session"""
        if self.session:
            await self.session.close()
            self.session = None

    def get_next_api_key(self) -> str:
        """Get next API key (round-robin) - kept for compatibility"""
        if not self.api_keys:
            return ""
        api_key = self.api_keys[self.current_api_key_index]
        self.current_api_key_index = (
            self.current_api_key_index + 1) % len(self.api_keys)
        return api_key

    async def process_batch(self, urls: List[str]) -> List[ProcessingResult]:
        """Process a batch of URLs"""
        # Ensure session is initialized and valid
        if not self.session or self.session.closed:
            if self.session and self.session.closed:
                self.session = None
            self.start_processing()

        # Create tasks for concurrent processing
        tasks = []
        for url in urls:
            task = asyncio.create_task(self.process_single_url(url))
            tasks.append(task)

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(ProcessingResult(
                    url=urls[i],
                    success=False,
                    error=str(result),
                    processing_time=0.0
                ))
            else:
                processed_results.append(result)

        return processed_results

    async def process_single_url(self, url: str) -> ProcessingResult:
        """Process a single image URL"""
        start_time = time.time()

        try:
            # Process image with API endpoint
            analysis = await self._analyze_image(url)

            return ProcessingResult(
                url=url,
                success=True,
                analysis=analysis,
                processing_time=time.time() - start_time,
                phone_number=analysis.get('phone_number', False)
            )

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return ProcessingResult(
                url=url,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )

    async def _analyze_image(self, image_url: str) -> Dict[str, Any]:
        """Analyze image using API endpoint"""
        # Use configured API endpoint (fall back to configured default address if needed)
        api_url = getattr(config, 'api_endpoint_url',
                          None) or "http://34.66.92.16:8000/generate"

        prompt = """
Analyze this image and determine if it shows a physical store or business location.
Please provide a JSON response with the following structure:
{
    "store_image": true/false,
    "text_content": ["any", "visible", "text", "in", "the", "image"],
    "store_name": "name of the store if visible",
    "business_contact": ["phone number", "email", "or website if visible"],
    "image_description": "brief description of what the image shows"
}
Guidelines:
- store_image should be true if this shows a physical retail store, restaurant, shop, or business establishment
- Extract any visible text including store names, signs, phone numbers, websites
- Be concise but accurate in descriptions
- If uncertain about store_image, err on the side of false
"""

        try:
            # Prepare form data
            data = aiohttp.FormData()
            data.add_field('text', prompt.strip())
            data.add_field('image_url', image_url)

            # Prepare headers (some servers require a User-Agent)
            headers = {'User-Agent': 'ImageAnalyzerEnterprise/1.0'}

            # Make API request with simple retry logic for transient network errors
            response_text = None
            last_exception = None
            for attempt in range(max(1, getattr(config, 'retry_attempts', 3))):
                try:
                    async with self.session.post(api_url, data=data, headers=headers) as response:
                        if response.status != 200:
                            raise Exception(
                                f"API request failed with status {response.status}")

                        response_text = await response.text()
                        # successful request, break out of retry loop
                        last_exception = None
                        break

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    # Transient network error or timeout - record and retry if attempts remain
                    last_exception = e
                    logger.warning(
                        "Transient error calling API for %s (attempt %d/%d): %s",
                        image_url, attempt +
                        1, getattr(config, 'retry_attempts', 3), repr(e)
                    )
                    # Exponential backoff before retrying (small, bounded)
                    await asyncio.sleep(min(10, getattr(config, 'retry_delay', 2.0) * (2 ** attempt)))

            if response_text is None:
                # Retries exhausted or an immediate non-retriable error occurred
                if last_exception:
                    # Raise the last caught network exception
                    logger.exception(
                        "Exhausted retries calling API for %s", image_url)
                    raise last_exception
                else:
                    raise Exception("Failed to retrieve API response")

            # Parse response - handle both direct JSON and markdown-wrapped JSON
            try:
                # Try direct JSON parsing first
                # Note: some servers may return text-wrapped JSON, so fall back to parsing
                api_response = json.loads(response_text)
            except Exception:
                # If not JSON, try to parse as text and extract JSON from markdown
                api_response = self._parse_api_response(response_text)

            # Defensive checks: ensure we received a dict-like response
            if api_response is None:
                # API returned literal `null` or empty body
                raise Exception(
                    f"API returned empty/null response for {image_url}: {response_text[:500]}")

            if not isinstance(api_response, dict):
                # Unexpected response shape (e.g., list or string). Include snippet for debugging.
                raise Exception(
                    f"Unexpected API response type {type(api_response).__name__} for {image_url}. Response snippet: {str(response_text)[:500]}"
                )

            # Check for API error responses (status 200 but with error details)
            if 'detail' in api_response and isinstance(api_response['detail'], str):
                if 'invalid' in api_response['detail'].lower() or 'error' in api_response['detail'].lower():
                    raise Exception(
                        f"API returned error: {api_response['detail']}")

            # Extract the analysis from the response
            if 'response' in api_response:
                # Handle nested response structure
                analysis_text = api_response['response']
                if isinstance(analysis_text, str):
                    # Remove markdown code blocks if present
                    if analysis_text.startswith('```json') and analysis_text.endswith('```'):
                        analysis_text = analysis_text[7:-3].strip()
                    elif analysis_text.startswith('```') and analysis_text.endswith('```'):
                        analysis_text = analysis_text[3:-3].strip()

                    try:
                        analysis_data = json.loads(analysis_text)
                    except json.JSONDecodeError:
                        raise Exception(
                            f"Failed to parse API response JSON: {analysis_text}")
                else:
                    analysis_data = analysis_text
            else:
                # Direct response structure
                analysis_data = api_response

            # Validate and normalize the response
            analysis = self._normalize_api_response(analysis_data)

            return analysis

        except Exception as e:
            # Log full traceback and exception type for easier debugging
            logger.exception("Error calling API for %s: %s",
                             image_url, repr(e))
            raise

    def _parse_api_response(self, response_text: str) -> Dict[str, Any]:
        """Parse API response that might be wrapped in markdown"""
        # Try to extract JSON from markdown code blocks
        if '```json' in response_text:
            # Extract content between ```json and ```
            start = response_text.find('```json')
            end = response_text.find('```', start + 7)
            if end != -1:
                json_content = response_text[start + 7:end].strip()
                return json.loads(json_content)
        elif '```' in response_text:
            # Extract content between ``` and ```
            start = response_text.find('```')
            end = response_text.find('```', start + 3)
            if end != -1:
                json_content = response_text[start + 3:end].strip()
                return json.loads(json_content)

        # Try to parse the entire response as JSON
        return json.loads(response_text)

    def _normalize_api_response(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize API response to expected format"""
        # Ensure all expected fields are present with defaults
        normalized = {
            'store_image': bool(api_data.get('store_image', False)),
            'text_content': api_data.get('text_content', []),
            'store_name': api_data.get('store_name', ''),
            'business_contact': api_data.get('business_contact', []),
            'image_description': api_data.get('image_description', ''),
            'phone_number': False
        }

        # Ensure text_content is a list
        if isinstance(normalized['text_content'], str):
            normalized['text_content'] = [normalized['text_content']]
        elif not isinstance(normalized['text_content'], list):
            normalized['text_content'] = []

        # Ensure business_contact is a list
        if isinstance(normalized['business_contact'], str):
            normalized['business_contact'] = [normalized['business_contact']]
        elif not isinstance(normalized['business_contact'], list):
            normalized['business_contact'] = []

        # Set phone_number based on whether business_contact contains phone-like data
        normalized['phone_number'] = bool(normalized['business_contact'])

        return normalized

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL (for caching, non-security use)"""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


# Global instance for easy access
image_processor = ImageProcessor()
