"""
Image processing module using Gemini AI for enterprise batch processing
"""
import asyncio
import aiohttp
import logging
import time
import hashlib
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import google.generativeai as genai
from PIL import Image
import io
import requests

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


class ImageProcessor:
    """Enterprise image processor using Gemini AI"""

    def __init__(self, api_keys: List[str] = None, max_workers: int = 10,
                 image_max_size: int = 2048):
        self.api_keys = api_keys or config.api_keys_list
        self.max_workers = max_workers
        self.image_max_size = image_max_size
        self.current_api_key_index = 0
        self.session: Optional[aiohttp.ClientSession] = None

        # Configure Gemini AI with the first API key
        if self.api_keys:
            genai.configure(api_key=self.api_keys[0])
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        else:
            logger.warning("No API keys provided for ImageProcessor")
            self.model = None

        logger.info(
            f"ImageProcessor initialized with {len(self.api_keys)} API keys")

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
        """Get next API key (round-robin)"""
        if not self.api_keys:
            raise ValueError("No API keys available")

        api_key = self.api_keys[self.current_api_key_index]
        self.current_api_key_index = (
            self.current_api_key_index + 1) % len(self.api_keys)
        return api_key

    async def process_batch(self, urls: List[str]) -> List[ProcessingResult]:
        """Process a batch of URLs"""
        if not self.session:
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
            # Download image
            image_data = await self._download_image(url)
            if not image_data:
                return ProcessingResult(
                    url=url,
                    success=False,
                    error="Failed to download image",
                    processing_time=time.time() - start_time
                )

            # Process image with Gemini AI
            analysis = await self._analyze_image(image_data)

            return ProcessingResult(
                url=url,
                success=True,
                analysis=analysis,
                processing_time=time.time() - start_time
            )

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            return ProcessingResult(
                url=url,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )

    async def _download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    content_type = response.headers.get('content-type', '')
                    if 'image' in content_type.lower():
                        image_data = await response.read()

                        # Resize image if too large
                        return self._resize_image_if_needed(image_data)
                    else:
                        logger.warning(
                            f"URL {url} is not an image (content-type: {content_type})")
                        return None
                else:
                    logger.warning(
                        f"Failed to download {url}: HTTP {response.status}")
                    return None

        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None

    def _resize_image_if_needed(self, image_data: bytes) -> bytes:
        """Resize image if it's too large"""
        try:
            image = Image.open(io.BytesIO(image_data))

            # Check if resizing is needed
            if max(image.width, image.height) > self.image_max_size:
                # Calculate new dimensions maintaining aspect ratio
                ratio = self.image_max_size / max(image.width, image.height)
                new_width = int(image.width * ratio)
                new_height = int(image.height * ratio)

                # Resize image
                resized_image = image.resize(
                    (new_width, new_height), Image.Resampling.LANCZOS)

                # Convert back to bytes
                output = io.BytesIO()
                format = image.format or 'JPEG'
                resized_image.save(output, format=format,
                                   quality=85, optimize=True)
                return output.getvalue()

            return image_data

        except Exception as e:
            logger.warning(f"Error resizing image: {e}")
            return image_data

    async def _analyze_image(self, image_data: bytes) -> Dict[str, Any]:
        """Analyze image using Gemini AI"""
        if not self.model:
            raise ValueError("Gemini AI model not initialized")

        try:
            # Prepare image for Gemini
            image = Image.open(io.BytesIO(image_data))

            # Create prompt for store image analysis
            prompt = """
            Analyze this image and determine if it shows a physical store or business location. 
            
            Please provide a JSON response with the following structure:
            {
                "store_image": true/false,
                "text_content": "any visible text in the image",
                "store_name": "name of the store if visible",
                "business_contact": "phone number, email, or website if visible",
                "image_description": "brief description of what the image shows"
            }
            
            Guidelines:
            - store_image should be true if this shows a physical retail store, restaurant, shop, or business establishment
            - Extract any visible text including store names, signs, phone numbers, websites
            - Be concise but accurate in descriptions
            - If uncertain about store_image, err on the side of false
            """

            # Generate content with current API key
            api_key = self.get_next_api_key()
            genai.configure(api_key=api_key)

            # Use ThreadPoolExecutor for the blocking Gemini API call
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                response = await loop.run_in_executor(
                    executor,
                    lambda: self.model.generate_content([prompt, image])
                )

            # Parse response
            if response and response.text:
                # Try to extract JSON from response
                response_text = response.text.strip()

                # Remove markdown code blocks if present
                if response_text.startswith('```json'):
                    response_text = response_text[7:]
                if response_text.endswith('```'):
                    response_text = response_text[:-3]

                try:
                    import json
                    analysis = json.loads(response_text)

                    # Validate required fields
                    required_fields = ['store_image', 'text_content', 'store_name',
                                       'business_contact', 'image_description']
                    for field in required_fields:
                        if field not in analysis:
                            analysis[field] = None

                    # Ensure store_image is boolean
                    if isinstance(analysis['store_image'], str):
                        analysis['store_image'] = analysis['store_image'].lower() in [
                            'true', 'yes', '1']

                    return analysis

                except json.JSONDecodeError:
                    # If JSON parsing fails, create structured response from text
                    return {
                        'store_image': False,
                        'text_content': response_text,
                        'store_name': None,
                        'business_contact': None,
                        'image_description': response_text[:200]
                    }
            else:
                raise ValueError("Empty response from Gemini AI")

        except Exception as e:
            logger.error(f"Error analyzing image with Gemini AI: {e}")
            raise

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL (for caching, non-security use)"""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


# Global instance for easy access
image_processor = ImageProcessor()
