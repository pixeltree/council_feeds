#!/usr/bin/env python3
"""
Agenda Parser for Calgary Council Stream Recorder.
Extracts expected speaker names from meeting agenda HTML pages.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re


def extract_speakers(agenda_url: Optional[str], timeout: int = 10) -> List[Dict[str, str]]:
    """
    Extract speaker names from a meeting agenda HTML page.

    Args:
        agenda_url: URL to the meeting agenda HTML page
        timeout: Request timeout in seconds (default: 10)

    Returns:
        List of dictionaries with speaker information:
        [{"name": str, "role": str, "confidence": str}, ...]
        Returns empty list on any failure (graceful degradation)
    """
    # Handle missing or empty URL
    if not agenda_url or not agenda_url.strip():
        print("[AGENDA] No agenda URL provided")
        return []

    print(f"[AGENDA] Fetching agenda from {agenda_url}")

    try:
        # Fetch the HTML page with timeout
        response = requests.get(agenda_url, timeout=timeout)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract speakers using multiple strategies
        speakers = []

        # Strategy 1: Find council members from common patterns
        speakers.extend(_extract_council_members(soup))

        # Strategy 2: Find presenters from presentation sections
        speakers.extend(_extract_presenters(soup))

        # Strategy 3: Find delegation names from public hearing sections
        speakers.extend(_extract_delegations(soup))

        # Deduplicate speakers by name (case-insensitive)
        unique_speakers = _deduplicate_speakers(speakers)

        if unique_speakers:
            print(f"[AGENDA] Found {len(unique_speakers)} potential speakers")
        else:
            print("[AGENDA] WARNING: No speakers found in agenda")

        return unique_speakers

    except requests.Timeout:
        print(f"[AGENDA] ERROR: Timeout fetching agenda from {agenda_url}")
        return []
    except requests.RequestException as e:
        print(f"[AGENDA] ERROR: Failed to fetch agenda: {e}")
        return []
    except Exception as e:
        print(f"[AGENDA] ERROR: Failed to parse agenda: {e}")
        return []


def _extract_council_members(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Extract council member names from HTML.

    Common patterns:
    - "Councillor FirstName LastName"
    - "Mayor FirstName LastName"
    - Lists of council members
    """
    members = []

    # Pattern 1: Search for text containing "Councillor" or "Mayor"
    # Use [ \t] to match only spaces/tabs, not newlines
    councillor_pattern = re.compile(r'\b(Councillor|Mayor|Cllr\.?)[ \t]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*)', re.IGNORECASE)

    # Search in individual lines to avoid matching across newlines
    text_content = soup.get_text()
    for line in text_content.split('\n'):
        matches = councillor_pattern.findall(line)
        for title, name in matches:
            name = name.strip()
            if name and len(name) > 3:  # Basic validation
                members.append({
                    'name': name,
                    'role': title.capitalize(),
                    'confidence': 'high'
                })

    # Pattern 2: Look for common HTML structures (tables, lists)
    # Search for elements that might contain member lists
    for element in soup.find_all(['table', 'ul', 'ol']):
        # Look for cells/items containing council member patterns
        for cell in element.find_all(['td', 'th', 'li']):
            text = cell.get_text().strip()
            matches = councillor_pattern.findall(text)
            for title, name in matches:
                name = name.strip()
                if name and len(name) > 3:
                    members.append({
                        'name': name,
                        'role': title.capitalize(),
                        'confidence': 'high'
                    })

    # Deduplicate within this function (same person found multiple times)
    return _deduplicate_speakers(members)


def _extract_presenters(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Extract presenter names from presentation sections.

    Common patterns:
    - "Presenter: FirstName LastName"
    - "Presentation by FirstName LastName"
    """
    presenters = []

    # Pattern: "Presenter:" or "Presentation by" followed by name
    # Use [ \t] to match only spaces/tabs, not newlines
    presenter_pattern = re.compile(
        r'\b(Presenter|Presentation[ \t]+by|Presented[ \t]+by)[\s:]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*)',
        re.IGNORECASE
    )

    text_content = soup.get_text()
    for line in text_content.split('\n'):
        matches = presenter_pattern.findall(line)
        for _, name in matches:
            name = name.strip()
            if name and len(name) > 3:
                presenters.append({
                    'name': name,
                    'role': 'Presenter',
                    'confidence': 'medium'
                })

    # Deduplicate within this function
    return _deduplicate_speakers(presenters)


def _extract_delegations(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Extract delegation/speaker names from public hearing sections.

    Common patterns:
    - "Delegation: FirstName LastName"
    - "Speaker: FirstName LastName"
    - Public hearing lists
    """
    delegations = []

    # Pattern: "Delegation:" or "Speaker:" followed by name
    # Use [ \t] to match only spaces/tabs, not newlines
    delegation_pattern = re.compile(
        r'\b(Delegation|Speaker|Deputation)[\s:]+([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*)',
        re.IGNORECASE
    )

    text_content = soup.get_text()
    for line in text_content.split('\n'):
        matches = delegation_pattern.findall(line)
        for _, name in matches:
            name = name.strip()
            if name and len(name) > 3:
                delegations.append({
                    'name': name,
                    'role': 'Delegation',
                    'confidence': 'medium'
                })

    # Deduplicate within this function
    return _deduplicate_speakers(delegations)


def _deduplicate_speakers(speakers: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Remove duplicate speakers based on name (case-insensitive).
    Prefers higher confidence entries.
    """
    # Confidence ordering
    confidence_order = {'high': 3, 'medium': 2, 'low': 1}

    seen = {}  # lowercase name -> speaker dict

    for speaker in speakers:
        name_lower = speaker['name'].lower()

        if name_lower not in seen:
            seen[name_lower] = speaker
        else:
            # Keep the one with higher confidence
            existing_conf = confidence_order.get(seen[name_lower].get('confidence', 'low'), 0)
            new_conf = confidence_order.get(speaker.get('confidence', 'low'), 0)

            if new_conf > existing_conf:
                seen[name_lower] = speaker

    return list(seen.values())
