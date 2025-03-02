from __future__ import annotations

import logging
import re
import urllib.parse

logger = logging.getLogger(__name__)


def clean_episode_url(url: str) -> str:
    """Clean podcast episode URL by removing tracking redirects and unwanted parameters.

    This function:
    1. Parses the URL to identify redirect trackers (multiple domains in the path)
    2. Extracts the last/final domain which is likely the actual media host
    3. Keeps only whitelisted URL parameters that are essential for media access
    4. Handles URL-encoded URLs in the path (e.g., anchor.fm and similar hosts)

    Args:
        url: Original episode URL with potential tracking redirects

    Returns:
        Cleaned URL pointing directly to the media file
    """
    # First, check for URL-encoded URLs in the path (common with anchor.fm and others)
    # Look for patterns like /https%3A%2F%2F... or /play/12345/https%3A%2F%2F...
    encoded_url_pattern = re.compile(r'(/[^/]*/)?(https?%3A%2F%2F[^?&]+)')
    match = encoded_url_pattern.search(url)

    if match:
        # Found a URL-encoded URL, decode it and use that instead
        encoded_url = match.group(2)
        decoded_url = urllib.parse.unquote(encoded_url)
        logger.debug("Found URL-encoded URL: %s", decoded_url)
        return clean_episode_url(decoded_url)

    # Parse the URL
    parsed_url = urllib.parse.urlparse(url)

    # Get the path and remove any leading/trailing slashes
    path = parsed_url.path.strip('/')

    # Check for path segments that might be encoded URLs
    path_parts = path.split('/')
    for part in path_parts:
        if part.startswith(('http%3A', 'https%3A')):
            # Found a URL-encoded URL part
            decoded_part = urllib.parse.unquote(part)
            logger.debug("Found URL-encoded path part: %s", decoded_part)
            return clean_episode_url(decoded_part)

    # Parameters to keep (whitelist)
    # Add any essential parameters for media access here
    whitelist_params = {
        'token-hash', 'token-time', 'token', 'expires', 'signature', 'auth', 'updated', 'key', 'k', 's', 'sapid',
    }

    # Look for the last domain in the path (ignoring common file extensions)
    final_domain = parsed_url.netloc
    final_path: list[str] = []
    domain_pattern = re.compile(r'^[a-zA-Z0-9][-a-zA-Z0-9]*(\.[a-zA-Z0-9][-a-zA-Z0-9]*)+$')

    # Common URL redirect prefixes
    redirect_indicators = {'redirect', 'traffic', 'measure', 'track'}

    # Track if we're still in redirect prefixes
    in_redirect_chain = True
    for i, part in enumerate(path_parts):
        # Check if this part looks like a domain
        if domain_pattern.match(part) and '.' in part and i != len(path_parts) - 1:
            # This is likely a domain in a redirect chain
            final_domain = part
            final_path = []  # Reset path since we found a new domain
            in_redirect_chain = True
            continue
        elif in_redirect_chain and any(x in part for x in redirect_indicators):
            # Skip common redirect indicators
            continue

        # Once we've passed the redirect chain, start collecting the actual path
        in_redirect_chain = False
        final_path.append(part)

    # Reconstruct the path
    clean_path = '/'.join(final_path) if final_path else '/'.join(path_parts)

    # Filter URL parameters to keep only whitelisted ones
    query_params = urllib.parse.parse_qs(parsed_url.query)
    filtered_params = {k: v for k, v in query_params.items() if k.lower() in whitelist_params}

    # Rebuild the URL with the final domain and filtered parameters
    clean_query = urllib.parse.urlencode(filtered_params, doseq=True) if filtered_params else ''

    # Construct the clean URL
    scheme = parsed_url.scheme if parsed_url.scheme else 'https'
    clean_url = urllib.parse.urlunparse((
        scheme,
        final_domain,
        f'/{clean_path}' if clean_path else '',
        '',
        clean_query,
        '',
    ))

    if url != clean_url:
        logger.debug("Cleaned URL: %s -> %s", url, clean_url)

    return clean_url
