#!/usr/bin/env python3
"""
Simple link checker for markdown files in the repo.
Validates internal file links and warns about external URLs.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse


def find_markdown_files():
    """Find all .md files in the repo."""
    md_files = []
    for root, dirs, files in os.walk('.'):
        # Skip hidden dirs and common exclude paths
        dirs[:] = [d for d in dirs if not d.startswith(
            '.') and d not in ['__pycache__', 'node_modules']]
        for file in files:
            if file.endswith('.md'):
                md_files.append(os.path.join(root, file))
    return sorted(md_files)


def extract_links(md_content):
    """Extract markdown links [text](link) from content."""
    # Match [text](link) pattern
    pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
    return re.findall(pattern, md_content)


def check_link(link, md_file):
    """Check if a link is valid (file existence or URL format)."""
    errors = []

    # Parse URL to check if external
    parsed = urlparse(link)

    # External URL (http, https, mailto, etc.)
    if parsed.scheme in ('http', 'https', 'mailto', 'ftp'):
        return None  # Skip external URL validation

    # Local file link
    if '#' in link:
        # Has anchor, extract file part
        file_part = link.split('#')[0]
    else:
        file_part = link

    # Empty file part means current file
    if not file_part:
        return None

    # Resolve relative path
    md_dir = os.path.dirname(md_file)
    target_path = os.path.normpath(os.path.join(md_dir, file_part))

    # Check if file exists
    if not os.path.exists(target_path):
        return f"Broken link: '{link}' (target: {target_path})"

    return None


def main():
    """Check all markdown files for broken links."""
    md_files = find_markdown_files()

    if not md_files:
        print("❌ No markdown files found")
        return 1

    print(f"📄 Found {len(md_files)} markdown file(s):\n")

    total_links = 0
    broken_links = []

    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️  Error reading {md_file}: {e}")
            continue

        links = extract_links(content)
        if not links:
            print(f"  ✓ {md_file} (no links)")
            continue

        file_errors = []
        for text, link in links:
            total_links += 1
            error = check_link(link, md_file)
            if error:
                file_errors.append((link, error))
                broken_links.append((md_file, link, error))

        if file_errors:
            print(f"  ❌ {md_file} ({len(links)} links)")
            for link, error in file_errors:
                print(f"     - {error}")
        else:
            print(f"  ✓ {md_file} ({len(links)} links)")

    print(f"\n{'='*70}")
    print(f"📊 Summary:")
    print(f"  Total files: {len(md_files)}")
    print(f"  Total links: {total_links}")
    print(f"  Broken links: {len(broken_links)}")

    if broken_links:
        print(f"\n❌ {len(broken_links)} broken link(s) found:")
        for md_file, link, error in broken_links:
            print(f"  {md_file}: {error}")
        return 1
    else:
        print("\n✅ All links valid!")
        return 0


if __name__ == '__main__':
    exit(main())
