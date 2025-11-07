"""
Image processing module using OCR for enterprise batch processing
"""
import asyncio
import aiohttp
import logging
import time
import hashlib
import os
import tempfile
import re
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
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
    ocr_engine_used: Optional[str] = None


class ImageProcessor:
    """Enterprise image processor using OCR"""

    def __init__(self, api_keys: List[str] = None, max_workers: int = 10,
                 image_max_size: int = 2048):
        self.api_keys = api_keys or config.api_keys_list
        self.max_workers = max_workers
        self.image_max_size = image_max_size
        self.current_api_key_index = 0
        self.session: Optional[aiohttp.ClientSession] = None

        logger.info(
            f"ImageProcessor initialized with OCR processing")

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
            # Download image
            image_data = await self._download_image(url)
            if not image_data:
                return ProcessingResult(
                    url=url,
                    success=False,
                    error="Failed to download image",
                    processing_time=time.time() - start_time
                )

            # Process image with OCR
            analysis, ocr_engine = await self._analyze_image(image_data)

            return ProcessingResult(
                url=url,
                success=True,
                analysis=analysis,
                processing_time=time.time() - start_time,
                phone_number=analysis.get('phone_number', False),
                ocr_engine_used=ocr_engine
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
        """Analyze image using OCR"""
        # Save image data to temporary file for OCR processing
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
            temp_file.write(image_data)
            temp_path = temp_file.name

        try:
            # Use ThreadPoolExecutor for the blocking OCR operations
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                result = await loop.run_in_executor(
                    executor,
                    lambda: self._process_image_ocr(temp_path)
                )

            # Convert result to expected format
            analysis = {
                'store_image': result['store_image'] == 'Yes',
                'text_content': result['text_content'],
                'store_name': result['store_name'],
                'business_contact': result['business_contact'],
                'image_description': result['image_description'],
                # Set based on whether phones were found
                'phone_number': bool(result['business_contact'])
            }

            return analysis, "easyocr+pytesseract"

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _detect_compute_device(self):
        """Return compute device string: 'cuda', 'mps', or 'cpu' and a gpu boolean usable for EasyOCR."""
        try:
            import torch
        except Exception:
            return 'cpu', False
        try:
            if getattr(torch, 'cuda', None) and torch.cuda.is_available():
                return 'cuda', True
            # macOS MPS support
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return 'mps', True
        except Exception:
            pass
        return 'cpu', False

    def _run_easyocr(self, img_path, langs=None):
        try:
            import easyocr
        except Exception:
            return None
        # Normalize langs: accept comma-separated string, list/tuple, or None
        if langs is None:
            langs_list = [
                # Removed unsupported: 'ml', 'gu', 'pa', 'or', 'ta', 'te', 'bn', 'kn', 'mr'
                'en', 'hi',
            ]
        else:
            if isinstance(langs, str):
                parts = [p.strip() for p in langs.split(',') if p.strip()]
                langs_list = parts if parts else ['en']
            elif isinstance(langs, (list, tuple)):
                langs_list = list(langs)
            else:
                langs_list = ['en']

        # Detect compute device and pass gpu flag to EasyOCR when available
        device, gpu_available = self._detect_compute_device()

        # Create reader, be defensive: some installs of EasyOCR don't support every lang code
        try:
            reader = easyocr.Reader(langs_list, gpu=gpu_available)
        except Exception as e:
            # Better parsing: detect which of the requested lang codes are mentioned as unsupported
            try:
                msg = str(e)
                unsupported = set()
                # 1) look for set/list literals like {'ml', 'gu'} or ['ml','gu']
                m = re.search(r"\{([^}]*)\}", msg)
                if m:
                    codes = re.findall(r"[A-Za-z0-9_]+", m.group(1))
                    unsupported.update(codes)
                m2 = re.search(r"\[([^]]*)\]", msg)
                if m2:
                    codes2 = re.findall(r"[A-Za-z0-9_]+", m2.group(1))
                    unsupported.update(codes2)
                # 2) also check for occurrences of requested codes as whole words in the message
                for code in langs_list:
                    if re.search(r"\b" + re.escape(code) + r"\b", msg):
                        unsupported.add(code)
                # 3) filter to only those that were requested (avoid accidental matches)
                unsupported = set([c for c in unsupported if c in langs_list])
                filtered = [l for l in langs_list if l not in unsupported]
                if filtered:
                    try:
                        reader = easyocr.Reader(filtered, gpu=gpu_available)
                    except Exception:
                        reader = None
                else:
                    reader = None
            except Exception:
                reader = None

            if reader is None:
                # Log the error and retry with English-only to avoid crashing
                try:
                    reader = easyocr.Reader(['en'], gpu=gpu_available)
                except Exception:
                    return None

        results = reader.readtext(img_path, detail=1)

        # results is list of (bbox, text, conf)
        entries = []
        for bbox, text, conf in results:
            if not text or not text.strip():
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x, y, x2, y2 = int(min(xs)), int(
                min(ys)), int(max(xs)), int(max(ys))
            entries.append({
                'text': text.strip(),
                'conf': float(conf) if conf is not None else None,
                'bbox': (x, y, x2 - x, y2 - y),  # x, y, w, h
            })
        return entries

    def _run_pytesseract(self, img_path, langs=None):
        try:
            import pytesseract
        except Exception:
            return []
        from PIL import Image
        from pytesseract import Output
        img = Image.open(img_path)
        try:
            # If langs provided, convert comma-separated to Tesseract format e.g. 'hin,eng' -> 'hin+eng'
            tess_lang = None
            if langs:
                if isinstance(langs, str):
                    parts = [p.strip() for p in langs.split(',') if p.strip()]
                    if parts:
                        tess_lang = '+'.join(parts)
            if tess_lang:
                data = pytesseract.image_to_data(
                    img, output_type=Output.DICT, lang=tess_lang)
            else:
                data = pytesseract.image_to_data(img, output_type=Output.DICT)
        except Exception:
            # fallback to simple string
            txt = pytesseract.image_to_string(img)
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            return [{'text': t, 'conf': None, 'bbox': (0, 0, img.width, 0)} for t in lines]
        entries = []
        n = len(data.get('text', []))
        for i in range(n):
            txt = data['text'][i].strip()
            if not txt:
                continue
            x = int(data['left'][i])
            y = int(data['top'][i])
            w = int(data['width'][i])
            h = int(data['height'][i])
            conf = None
            try:
                conf = float(data.get('conf', [None] * n)[i])
            except Exception:
                conf = None
            entries.append({'text': txt, 'conf': conf, 'bbox': (x, y, w, h)})
        return entries

    def _extract_phone_numbers(self, texts):
        # Join texts and search for phone patterns (Indian formats too)
        joined = "\n".join(texts)
        phones = set()
        # Common patterns
        patterns = [
            r"\+91[-\s]?\d{10}",
            r"0\d{10}",
            r"\b\d{10}\b",
            r"\b\d{5}[-\s]?\d{5}\b",
            r"\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b",
        ]
        for pat in patterns:
            for m in re.findall(pat, joined):
                phones.add(m)
        # Also capture spaced digits (e.g., 9 3 2 3 6 6 8 6 6 6)
        spaced = re.findall(r"(?:\+91[-\s]?|0)?(?:\d[\s-]){9}\d", joined)
        for s in spaced:
            phones.add(re.sub(r"[\s-]", '', s))
        return list(phones)

    def _rank_entries(self, entries, image_height):
        # compute a simple score: area * top_bias where top_bias favours text nearer top
        scored = []
        for e in entries:
            x, y, w, h = e.get('bbox', (0, 0, 0, 0))
            area = max(1, w * h)
            # vertical center relative (0 top, 1 bottom)
            vcenter = (y + h / 2) / max(1, image_height)
            top_bias = 1.0 + (1.0 - vcenter)  # closer to top -> higher
            score = area * top_bias
            scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _detect_sign_area(self, img_path):
        # Very simple heuristic: look for large rectangular bright/dark region that could be a sign.
        try:
            import cv2
            import numpy as np
        except Exception:
            return False
        img = cv2.imread(img_path)
        if img is None:
            return False
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # use morphological operations to find rectangular regions
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(
            blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area = cw * ch
            if area > 0.01 * (w * h):
                aspect = cw / max(ch, 1)
                if 1.5 < aspect < 15:  # wide rectangular sign
                    return True
        return False

    def _choose_store_name_from_entries(self, entries, image_height):
        if not entries:
            return ""
        keywords = [
            'hotel', 'restaurant', 'dhaba', 'store', 'shop', 'mart', 'salon', 'bakery',
            'cafe', 'clinic', 'emporium', 'bazar', 'bazaar', 'electronics', 'mobile', 'phon', 'kj'
        ]
        scored = self._rank_entries(entries, image_height)
        for score, e in scored:
            txt = e['text'].strip()
            lower = txt.lower()
            for kw in keywords:
                if kw in lower:
                    cleaned = re.sub(r'\b(pvt\.?|ltd\.?|private|limited)\b',
                                     '', txt, flags=re.I).strip(' -,.')
                    return cleaned
        best = None
        best_score = -1.0
        for score, e in scored:
            txt = e['text'].strip()
            if not txt or re.fullmatch(r'[\d\W]+', txt) or len(txt) < 2:
                continue
            digits = sum(1 for c in txt if c.isdigit())
            alpha = sum(1 for c in txt if c.isalpha() or ord(c) > 127)
            if alpha < 2:
                continue
            ratio = alpha / max(1, alpha + digits)
            cur_score = score * (0.6 + 0.4 * ratio) + alpha * 2
            if cur_score > best_score:
                best_score = cur_score
                best = txt
        if best:
            cleaned = re.sub(r'\b(pvt\.?|ltd\.?|private|limited)\b',
                             '', best, flags=re.I).strip(' -,.')
            return cleaned
        for e in entries:
            t = e['text'].strip()
            if any(c.isalpha() or ord(c) > 127 for c in t):
                return t
        return ""

    def _build_image_description(self, texts, store_name):
        # concise description up to 50 words
        if store_name:
            desc = f"Signage showing '{store_name}' with visible text and storefront elements."
        elif texts:
            desc = f"Storefront with visible signage and text: {texts[0]}"
        else:
            desc = "Image of a storefront or street scene; signage and text may be present."
        # limit to 50 words
        words = desc.split()
        return " ".join(words[:50])

    def _process_image_ocr(self, img_path, langs=None, tess_langs=None):
        if not os.path.exists(img_path):
            return {
                "store_image": "No",
                "text_content": [],
                "store_name": "",
                "business_contact": [],
                "image_description": ""
            }

        # load image height for ranking heuristics
        try:
            pil_img = Image.open(img_path)
            img_h = pil_img.height
        except Exception:
            img_h = 1000

        # Try EasyOCR first (returns entries with bbox), fallback to pytesseract entries
        ocr_entries = self._run_easyocr(img_path, langs=langs)
        if not ocr_entries:
            ocr_entries = self._run_pytesseract(img_path, langs=tess_langs)

        texts_u = []
        if ocr_entries:
            # sort entries by y (top->bottom) then x (left->right) to create reading order
            sorted_entries = sorted(ocr_entries, key=lambda e: (
                e.get('bbox', (0, 0, 0, 0))[1], e.get('bbox', (0, 0, 0, 0))[0]))
            seen = set()
            for e in sorted_entries:
                t = e.get('text', '').strip()
                if t and t not in seen:
                    seen.add(t)
                    texts_u.append(t)

        phones = self._extract_phone_numbers(texts_u)

        # determine if store
        store_yes = False
        store_name = ""
        if ocr_entries:
            store_name = self._choose_store_name_from_entries(
                ocr_entries, img_h)
        if store_name or phones:
            store_yes = True
        try:
            if self._detect_sign_area(img_path):
                store_yes = True
        except Exception:
            pass

        desc = self._build_image_description(texts_u, store_name)

        return {
            "store_image": "Yes" if store_yes else "No",
            "text_content": texts_u,
            "store_name": store_name,
            "business_contact": phones,
            "image_description": desc
        }

    def get_url_hash(self, url: str) -> str:
        """Generate hash for URL (for caching, non-security use)"""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()


# Global instance for easy access
image_processor = ImageProcessor()
