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
import os
from io import BytesIO
from PIL import Image, ImageOps

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

    def __init__(self, api_keys: List[str] = None, max_workers: Optional[int] = None):
        self.api_keys = api_keys or config.api_keys_list
        self.max_workers = max_workers if max_workers is not None else getattr(
            config, 'max_concurrent_workers', 5)
        self.current_api_key_index = 0
        self.session: Optional[aiohttp.ClientSession] = None

        logger.info(
            f"ImageProcessor initialized with API endpoint processing")
        logger.info(
            f"ImageProcessor initialized with API endpoint processing (max_workers={self.max_workers})")

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

    async def _download_and_resize_image(self, image_url: str, always_upload: bool = False) -> Optional[bytes]:
        """Download image and resize if larger than 800x600.

        Returns resized image bytes (JPEG) when resizing occurred, or None
        when download failed or resizing was not necessary.
        """
        # Ensure we have a session
        if not self.session or getattr(self.session, 'closed', False):
            self.start_processing()

        try:
            async with self.session.get(image_url) as img_resp:
                if img_resp.status != 200:
                    logger.debug(
                        'Image download returned non-200 %s for %s', img_resp.status, image_url)
                    return None

                img_bytes = await img_resp.read()

                try:
                    with Image.open(BytesIO(img_bytes)) as img:
                        img = ImageOps.exif_transpose(img)
                        w, h = img.size
                        # If image exceeds threshold, resize+pad to 512x512
                        if w > 640 or h > 640:
                            img = img.convert('RGB')
                            img.thumbnail((512, 512), Image.LANCZOS)
                            square = Image.new(
                                'RGB', (512, 512), (255, 255, 255))
                            paste_x = (512 - img.width) // 2
                            paste_y = (512 - img.height) // 2
                            square.paste(img, (paste_x, paste_y))
                            out_buf = BytesIO()
                            square.save(out_buf, format='JPEG', quality=85)
                            out_buf.seek(0)
                            return out_buf.read()

                        # If caller requested always_upload, return the image
                        # bytes (converted to JPEG) even when not resized.
                        if always_upload:
                            img = img.convert('RGB')
                            out_buf = BytesIO()
                            img.save(out_buf, format='JPEG', quality=85)
                            out_buf.seek(0)
                            return out_buf.read()

                except Exception:
                    logger.debug(
                        'Failed to open/process downloaded image for %s', image_url)
                    return None

        except Exception:
            logger.debug(
                'Failed to download image for local processing: %s', image_url)
            return None

        return None

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
            # Ensure processing session is available before attempting to
            # download/resize images locally. This covers cases where
            # `process_single_url` was called directly without prior
            # `start_processing()`.
            if not self.session or getattr(self.session, 'closed', False):
                self.start_processing()
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
"Analyze this image and determine if it shows a physical store or business location. Please provide a JSON response with the following structure: {\"store_image\": true/false, \"text_content\": \"any visible text in the image\", \"store_name\": \"name of the store if visible\", \"business_contact\": \"phone number, email, or website if visible\", \"image_description\": \"brief description of what the image shows\"} Guidelines: - store_image should be true if this shows a physical retail store, restaurant, shop, or business establishment - Extract any visible text including store names, signs, phone numbers, websites - Be concise but accurate in descriptions - If uncertain about store_image, err on the side of false"
"""

        try:
            # Attempt to download and resize the image before making the API request.
            # Respect config.skip_image_download; when disabled, pass
            # config.upload_always to control whether we always attach image bytes.
            resized_bytes = None
            if not getattr(config, 'skip_image_download', False):
                resized_bytes = await self._download_and_resize_image(image_url, always_upload=getattr(config, 'upload_always', False))

            # If configured for development debugging, save the actual bytes
            # we will send to the API so developers can inspect them later.
            if resized_bytes and getattr(config, 'development_mode', False) and getattr(config, 'store_sent_images', False):
                try:
                    # Ensure directories exist
                    config.create_directories()
                    filename = f"{self.get_url_hash(image_url)}_{int(time.time())}.jpg"
                    save_path = os.path.join(config.upload_dir, filename)
                    with open(save_path, 'wb') as f:
                        f.write(resized_bytes)
                    logger.debug('Saved sent image for %s to %s',
                                 image_url, save_path)
                except Exception:
                    logger.exception(
                        'Failed to save sent image for debugging: %s', image_url)

            # Prepare form data
            data = aiohttp.FormData()
            data.add_field('text', prompt.strip())
            # Attach resized image file when available; otherwise send image_url only.
            if resized_bytes:
                data.add_field('image', resized_bytes,
                               filename='resized.jpg', content_type='image/jpeg')
            else:
                # This line remains unchanged
                data.add_field('image_url', image_url)

            # Prepare headers (some servers require a User-Agent)
            headers = {'User-Agent': 'ImageAnalyzerEnterprise/1.0'}

            # Make API request with improved retry logging and clearer exception on exhaustion
            attempts = max(1, getattr(config, 'retry_attempts', 3))
            last_exception = None
            response_text = None

            for attempt in range(attempts):
                try:
                    logger.debug(
                        "Calling API %s (attempt %d/%d) timeout=%ss",
                        api_url,
                        attempt + 1,
                        attempts,
                        getattr(config, 'request_timeout', None),
                    )
                    async with self.session.post(api_url, data=data, headers=headers) as response:
                        body = await response.text()
                        if response.status != 200:
                            logger.warning(
                                "API returned non-200 status %s for %s (attempt %d/%d). Body snippet: %s",
                                response.status, image_url, attempt +
                                1, attempts, (body or "")[:1000]
                            )
                            raise Exception(
                                f"API request failed with status {response.status}")
                        response_text = body
                        last_exception = None
                        break

                except asyncio.TimeoutError as e:
                    last_exception = e
                    logger.warning(
                        "Timeout calling API for %s (attempt %d/%d). configured_timeout=%s",
                        image_url,
                        attempt + 1,
                        attempts,
                        getattr(config, 'request_timeout', None),
                    )
                    await asyncio.sleep(min(30, getattr(config, 'retry_delay', 2.0) * (2 ** attempt)))

                except aiohttp.ClientError as e:
                    last_exception = e
                    logger.warning(
                        "Network error calling API for %s (attempt %d/%d): %s",
                        image_url,
                        attempt + 1,
                        attempts,
                        repr(e),
                    )
                    await asyncio.sleep(min(30, getattr(config, 'retry_delay', 2.0) * (2 ** attempt)))

                except Exception as e:
                    last_exception = e
                    logger.error(
                        "Unexpected error calling API for %s (attempt %d/%d): %s",
                        image_url,
                        attempt + 1,
                        attempts,
                        repr(e),
                    )
                    # Do not retry on unexpected logic errors
                    break

            if response_text is None:
                logger.exception(
                    "Exhausted retries calling API for %s after %d attempts. last_exception=%s",
                    image_url,
                    attempts,
                    repr(last_exception),
                )
                if isinstance(last_exception, asyncio.TimeoutError):
                    raise Exception(
                        f"API request timed out after {attempts} attempts (timeout={getattr(config, 'request_timeout', None)}s) for {image_url}"
                    ) from last_exception
                elif last_exception:
                    raise last_exception
                else:
                    raise Exception(
                        "Failed to retrieve API response (unknown reason)")

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
