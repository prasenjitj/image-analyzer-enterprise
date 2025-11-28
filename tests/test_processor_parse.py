from src.processor import image_processor
import sys
import types
import pytest

# Insert a minimal fake src.enterprise_config so tests can import src.processor
cfg = types.SimpleNamespace(
    api_backend='openrouter',
    openrouter_api_key='test_key',
    max_concurrent_workers=2,
    request_timeout=10,
    skip_image_download=True,
    upload_always=False,
    development_mode=False,
    store_sent_images=False,
    upload_dir='/tmp',
    retry_attempts=1,
    retry_delay=1.0,
    create_directories=lambda: None,
)
mod = types.ModuleType('src.enterprise_config')
mod.config = cfg
sys.modules['src.enterprise_config'] = mod
sys.path.insert(0, '')


def test_direct_json_parsing():
    txt = '{"store_image": false, "text_content": "Canon", "store_name": "Canon", "business_contact": "", "image_description": "A Canon printer."}'
    parsed = image_processor._parse_api_response(txt)
    assert isinstance(parsed, dict)
    norm = image_processor._normalize_api_response(parsed)
    assert norm['store_name'] == 'Canon'
    assert norm['store_image'] is False


def test_fenced_json_parsing():
    txt = 'Answer:\n```json\n{"store_image": false, "text_content": ["Canon"], "store_name": "Canon"}\n```'
    parsed = image_processor._parse_api_response(txt)
    assert isinstance(parsed, dict)
    assert parsed.get('store_name') == 'Canon'


def test_inline_json_parsing():
    txt = 'prefix {"store_image": true, "text_content": ["Shop"], "store_name": "Shop"} suffix'
    parsed = image_processor._parse_api_response(txt)
    assert isinstance(parsed, dict)
    assert parsed.get('store_image') is True or str(
        parsed.get('store_image')).lower() == 'true'


def test_final_response_plain_parsing():
    txt = (
        'Final response: store_image: true\n'
        'text_content: "आशापुरा स्टोर्स", "Quality is our promise.", "9323688666"\n'
        'store_name: आशापुरा स्टोर्स\n'
        'business_contact: 9323688666\n'
        'image_description: A busy outdoor seating area at a restaurant or food stall named "आशापुरा स्टोर्स".'
    )
    parsed = image_processor._parse_api_response(txt)
    assert isinstance(parsed, dict)
    # ensure list splitting
    assert isinstance(parsed.get('text_content'), list)
    assert 'आशापुरा स्टोर्स' in parsed.get(
        'text_content')[0] or 'आशापुरा स्टोर्स' in parsed.get('store_name')
    norm = image_processor._normalize_api_response(parsed)
    assert norm['store_image'] is True
    assert norm['phone_number'] is True
