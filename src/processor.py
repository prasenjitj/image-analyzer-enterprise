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
    phone_number: bool = False


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

    async def _download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL"""
        try:
            logger.debug(f"Downloading image from {url}")
            if not self.session or self.session.closed:
                logger.warning(
                    f"Session is closed or None when downloading {url}")
                return None

            async with self.session.get(url) as response:
                logger.debug(f"Response status for {url}: {response.status}")
                if response.status == 200:
                    content_type = response.headers.get('content-type', '')
                    logger.debug(f"Content-type for {url}: {content_type}")
                    if 'image' in content_type.lower():
                        image_data = await response.read()
                        logger.debug(
                            f"Downloaded {len(image_data)} bytes for {url}")

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

                    # Normalize None -> False for now; we'll set it properly below
                    if analysis['store_image'] is None:
                        analysis['store_image'] = False

                    # Set store_image based solely on whether store_name contains valid text
                    def _is_valid_store_name(s):
                        if not s or not isinstance(s, str):
                            return False
                        s_clean = s.strip().lower()
                        if len(s_clean) < 2:
                            return False
                        for kw in ['not visible', 'none visible', 'no visible', 'not readable', 'none readable', 'unreadable', 'not legible', 'illegible', 'n/a', 'none', 'null', 'empty', 'no text', 'no name']:
                            if kw in s_clean:
                                return False
                        return True

                    # Store Front should be yes if and only if there is valid text for a store name
                    analysis['store_image'] = _is_valid_store_name(
                        analysis.get('store_name'))

                    # Extract phone number from business_contact
                    analysis['phone_number'] = self._extract_phone_number(
                        analysis.get('business_contact', ''))

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

    def _extract_phone_number(self, business_contact: str) -> bool:
        """Extract phone number from business contact text using improved regex patterns"""
        if not business_contact or business_contact.strip().upper() == 'N/A':
            return False

        import re

        # Improved phone number patterns - more specific to avoid false positives
        phone_patterns = [
            # International formats with country codes: +1 123-456-7890, +91 9876543210
            r'\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,4}',
            # US/Canada phone numbers: (123) 456-7890, 123-456-7890, 123.456.7890, 1234567890
            r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
            # UK phone numbers: 07123456789, 01234567890 (landlines and mobiles)
            # UK numbers start with 0 and are 10-11 digits total
            r'\b0\d{9,10}\b',
            # European formats: variations of XX XX XX XX XX
            r'\b\d{2,4}[-.\s]\d{2,4}[-.\s]\d{2,4}[-.\s]\d{2,4}(?:[-.\s]\d{2,4})?\b',
            # 10-digit mobile numbers without separators (common in some regions)
            # Exactly 10 digits, not followed by more digits
            r'\b\d{10}\b(?!\d)',
            # 11-digit numbers (US with country code, some international)
            r'\b\d{11}\b(?!\d)',  # Exactly 11 digits
        ]

        # Keywords that often precede phone numbers
        phone_keywords = [
            'phone', 'tel', 'telephone', 'call', 'contact', 'number', 'mobile', 'cell',
            'ph', 'tél', 'téléphone', 'fono', 'telefono', '手', '机', '电', '话',
            'contacto', 'numero', 'celular', 'móvil'
        ]

        # Keywords that suggest the number is NOT a phone number
        non_phone_keywords = [
            'invoice', 'account', 'id', 'order', 'reference', 'tracking', 'serial',
            'receipt', 'transaction', 'policy', 'claim', 'ticket', 'booking',
            'reservation', 'confirmation', 'code', 'pin', 'password', 'license'
        ]

        business_contact_lower = business_contact.lower()

        # Check if any phone keywords are present
        has_phone_keywords = any(
            keyword in business_contact_lower for keyword in phone_keywords)

        # Check if any non-phone keywords are present (strong negative signal)
        has_non_phone_keywords = any(
            keyword in business_contact_lower for keyword in non_phone_keywords)

        # If we have non-phone keywords, be very conservative
        if has_non_phone_keywords:
            return False

        # Check for phone number patterns
        for pattern in phone_patterns:
            if re.search(pattern, business_contact):
                # Additional validation for plain digit sequences to avoid false positives
                match = re.search(pattern, business_contact)
                if match:
                    phone_candidate = match.group(0)
                    clean_digits = re.sub(r'[^\d]', '', phone_candidate)

                    # For 10-digit numbers without separators, do additional validation
                    if len(clean_digits) == 10 and not any(char in phone_candidate for char in ['(', ')', '-', '.', ' ', '+']):
                        # Avoid numbers that look like dates (MMDDYY format)
                        if re.match(r'^\d{2}\d{2}\d{4}$', phone_candidate):
                            # Check if it looks like MM/DD/YYYY or similar date pattern
                            if re.match(r'^(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{4}$', phone_candidate):
                                return False  # Skip likely date patterns
                        # Only reject very obvious test sequences, not valid-looking numbers
                        if re.match(r'^(1111111111|2222222222|3333333333|4444444444|5555555555|6666666666|7777777777|8888888888|9999999999|0000000000|0123456789|9876543210)$', phone_candidate):
                            return False  # Skip obvious test sequences
                        # Allow sequential numbers like 1234567890 as they could be valid phone numbers
                        return True  # Valid 10-digit number

                # For 11-digit numbers, similar validation
                elif len(clean_digits) == 11 and not any(char in phone_candidate for char in ['(', ')', '-', '.', ' ', '+']):
                    # Avoid obvious test sequences for 11 digits
                    if re.match(r'^(12345678901|09876543210|11111111111)$', phone_candidate):
                        return False  # Reject test sequences

                    return True  # Valid 11-digit number

                # For other phone number formats that matched patterns, do basic validation
                elif 7 <= len(clean_digits) <= 15:
                    return True  # Valid phone number with separators or other formats
        # Only return True if we find a pattern that looks very phone-like after a keyword
        if has_phone_keywords:
            # Look for patterns like "phone: 123-456-7890" or "call 1234567890"
            keyword_pattern = r'(?:' + \
                '|'.join(phone_keywords) + r')[:\s]*([^\s,]+)'
            match = re.search(keyword_pattern, business_contact_lower)
            if match:
                potential_number = match.group(1)
                # Check if the potential number contains mostly digits and phone separators
                if re.match(r'^[\d\s\(\)\-\.\+]{7,}$', potential_number):
                    clean_number = re.sub(r'[^\d]', '', potential_number)
                    # Must be reasonable length for a phone number
                    if 7 <= len(clean_number) <= 15:
                        return True

        return False

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL (for caching, non-security use)"""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


# Global instance for easy access
image_processor = ImageProcessor()
