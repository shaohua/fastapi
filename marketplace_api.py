#!/usr/bin/env python3
"""
VS Code Marketplace API functions for fetching AI extensions.
"""

import requests
import json
import time
from typing import List, Dict, Any
import logging

# Set up logging
logger = logging.getLogger(__name__)

def make_marketplace_request(page_number: int = 1, page_size: int = 54):
    """Direct translation of the curl command to Python."""
    
    url = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
    
    headers = {
        'accept': 'application/json;api-version=7.2-preview.1;excludeUrls=true',
        'accept-language': 'en-US,en;q=0.9',
        'cache-control': 'no-cache',
        'content-type': 'application/json',
        'dnt': '1',
        'origin': 'https://marketplace.visualstudio.com',
        'pragma': 'no-cache',
        'priority': 'u=1, i',
        'referer': 'https://marketplace.visualstudio.com/search?target=VSCode&category=AI&sortBy=Installs',
        'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
        'x-tfs-fedauthredirect': 'Suppress',
        'x-tfs-session': '40c83018-808b-4b5c-beb9-6c0d89c95bd1'
    }
    
    cookies = {
        'VstsSession': '%7B%22PersistentSessionId%22%3A%229945b006-393a-4e79-b7f3-5ebfcbeeb631%22%2C%22PendingAuthenticationSessionId%22%3A%2200000000-0000-0000-0000-000000000000%22%2C%22CurrentAuthenticationSessionId%22%3A%2200000000-0000-0000-0000-000000000000%22%2C%22SignInState%22%3A%7B%7D%7D',
        'Gallery-Service-UserIdentifier': 'c8c72388-a057-442d-bbd1-25063657de9f',
        'Market_SelectedTab': 'vscode',
        'VSCodeOneClickInstallMessageOptOut': 'true',
        '_ga': 'GA1.3.1023046524.1751226526',
        'MSCC': 'NR',
        '_gid': 'GA1.3.150633483.1751753545'
    }
    
    data = {
        "assetTypes": [
            "Microsoft.VisualStudio.Services.Icons.Default",
            "Microsoft.VisualStudio.Services.Icons.Branding",
            "Microsoft.VisualStudio.Services.Icons.Small"
        ],
        "filters": [
            {
                "criteria": [
                    {"filterType": 8, "value": "Microsoft.VisualStudio.Code"},
                    {"filterType": 10, "value": "target:\"Microsoft.VisualStudio.Code\" "},
                    {"filterType": 12, "value": "37888"},
                    {"filterType": 5, "value": "AI"}
                ],
                "direction": 2,
                "pageSize": page_size,
                "pageNumber": page_number,
                "sortBy": 4,
                "sortOrder": 0,
                "pagingToken": None
            }
        ],
        "flags": 870
    }
    
    response = requests.post(url, headers=headers, cookies=cookies, json=data)
    return response

def extract_extensions(response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract extension information from API response."""
    extensions = []

    if not response_data or 'results' not in response_data:
        return extensions

    for result in response_data.get('results', []):
        for extension in result.get('extensions', []):
            ext_info = {
                'name': extension.get('displayName', 'Unknown'),
                'publisher': extension.get('publisher', {}).get('displayName', 'Unknown'),
                'extension_id': extension.get('extensionName', 'Unknown'),
                'publisher_id': extension.get('publisher', {}).get('publisherName', 'Unknown'),
                'version': extension.get('versions', [{}])[0].get('version', 'Unknown') if extension.get('versions') else 'Unknown',
                'install_count': None,
                'rating': None,
                'rating_count': None,
                'description': extension.get('shortDescription', ''),
                'tags': extension.get('tags', []),
                'categories': extension.get('categories', []),
                'published_date': extension.get('publishedDate', ''),
                'last_updated': extension.get('lastUpdated', ''),
                'flags': extension.get('flags', '')
            }

            # Extract statistics
            for stat in extension.get('statistics', []):
                stat_name = stat.get('statisticName', '')
                if stat_name == 'install':
                    ext_info['install_count'] = stat.get('value', 0)
                elif stat_name == 'averagerating':
                    ext_info['rating'] = stat.get('value', 0)
                elif stat_name == 'ratingcount':
                    ext_info['rating_count'] = stat.get('value', 0)

            extensions.append(ext_info)

    return extensions


def get_all_ai_extensions() -> List[Dict[str, Any]]:
    """Fetch all AI extensions by iterating through all pages."""
    all_extensions = []
    page_number = 1
    page_size = 100  # Increase page size for efficiency

    logger.info("Starting to fetch all AI extensions...")

    while True:
        logger.info(f"Fetching page {page_number}...")

        try:
            response = make_marketplace_request(page_number, page_size)

            if response.status_code != 200:
                logger.error(f"Error: HTTP {response.status_code}")
                break

            data = response.json()
            extensions = extract_extensions(data)

            if not extensions:
                logger.info(f"No more extensions found on page {page_number}")
                break

            all_extensions.extend(extensions)
            logger.info(f"Found {len(extensions)} extensions on page {page_number} (total: {len(all_extensions)})")

            # Check if we've reached the end by looking at actual results
            # If we got fewer results than requested, we're at the end
            if len(extensions) < page_size:
                logger.info(f"Reached end of results (got {len(extensions)} < {page_size})")
                break

            # Also check metadata if available
            try:
                total_count = data.get('results', [{}])[0].get('resultMetadata', [{}])[0].get('metadataItems', [])
                for item in total_count:
                    if item.get('name') == 'TotalCount':
                        total = int(item.get('value', 0))
                        if total > 0:  # Only trust positive total counts
                            logger.info(f"Total available extensions: {total}")
                            if len(all_extensions) >= total:
                                logger.info("All extensions fetched!")
                                return all_extensions
            except (IndexError, KeyError, ValueError):
                pass  # Ignore metadata parsing errors

            page_number += 1

            # Add a small delay to be respectful to the API
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Error on page {page_number}: {e}")
            break

    return all_extensions
