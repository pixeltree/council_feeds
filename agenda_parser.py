#!/usr/bin/env python3
"""
Agenda Parser for Calgary Council Stream Recorder.
Extracts expected speaker names from meeting agenda HTML pages.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import re
import json


def extract_speakers(agenda_url: Optional[str], timeout: int = 10, use_gemini: bool = True) -> List[Dict[str, str]]:
    """
    Extract speaker names from a meeting agenda HTML page.

    Args:
        agenda_url: URL to the meeting agenda HTML page
        timeout: Request timeout in seconds (default: 10)
        use_gemini: Whether to use Gemini AI for extraction (default: True)

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
        response = requests.get(agenda_url, timeout=timeout, verify=False)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Try Gemini AI extraction first if enabled
        if use_gemini:
            try:
                from config import GEMINI_API_KEY
                if GEMINI_API_KEY:
                    print("[AGENDA] Attempting Gemini AI extraction")
                    gemini_speakers = _extract_speakers_with_gemini(soup, GEMINI_API_KEY)
                    if gemini_speakers:
                        print(f"[AGENDA] Gemini AI found {len(gemini_speakers)} speakers")
                        return gemini_speakers
                    else:
                        print("[AGENDA] WARNING: Gemini AI returned no speakers")
                        # Don't fall back - this likely means no members in agenda
                        return []
                else:
                    print("[AGENDA] No Gemini API key configured, skipping AI extraction")
            except ImportError:
                print("[AGENDA] Gemini not available, skipping AI extraction")
            except Exception as e:
                print(f"[AGENDA] Gemini extraction failed: {e}")

        # Fallback to regex-based extraction
        speakers = []

        # Strategy 1: PRIORITY - Find "Members Present" section (highest confidence)
        members_present = _extract_members_present(soup)
        if members_present:
            print(f"[AGENDA] Found {len(members_present)} members in 'Members Present' section")
            speakers.extend(members_present)

        # Strategy 2: Find council members from common patterns
        speakers.extend(_extract_council_members(soup))

        # Strategy 3: Find presenters from presentation sections
        speakers.extend(_extract_presenters(soup))

        # Strategy 4: Find delegation names from public hearing sections
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


def _extract_speakers_with_gemini(soup: BeautifulSoup, api_key: str) -> List[Dict[str, str]]:
    """
    Use Gemini AI to extract speakers from HTML content via REST API.

    Args:
        soup: BeautifulSoup parsed HTML
        api_key: Gemini API key

    Returns:
        List of speaker dictionaries or empty list on failure
    """
    try:
        # Get clean text from HTML
        text_content = soup.get_text()

        # Limit text size to avoid token limits (first 10000 chars should contain Members Present)
        if len(text_content) > 10000:
            text_content = text_content[:10000]

        # Construct prompt
        prompt = f"""You are analyzing a Calgary City Council meeting agenda. Extract all members/speakers who attended the meeting.

Look specifically for sections titled:
- "Members Present"
- "Present"
- "In Attendance"
- "Attending Members"

Extract each person's name and their role/title. Common roles include:
- Mayor
- Councillor
- Chief Administrative Officer
- Representatives from various organizations

The text may have names concatenated together without spaces or line breaks. For example:
"Councillor M. AtkinsonCouncillor J. Smith" should be parsed as two separate people.

Agenda text:
{text_content}

Return ONLY a JSON array with this exact format (no markdown, no explanation, no code blocks):
[
  {{"name": "FirstName LastName", "role": "Mayor", "confidence": "high"}},
  {{"name": "FirstName LastName", "role": "Councillor", "confidence": "high"}}
]

If no members are found, return an empty array: []
"""

        # Use REST API directly with gemini-2.5-flash model
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={api_key}"

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048
            }
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()

        # Extract text from response
        if 'candidates' in result and len(result['candidates']) > 0:
            candidate = result['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                response_text = candidate['content']['parts'][0]['text'].strip()
            else:
                print("[AGENDA] Unexpected Gemini response structure")
                return []
        else:
            print("[AGENDA] No candidates in Gemini response")
            return []

        # Remove markdown code blocks if present
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith('```'):
                    in_code_block = not in_code_block
                    continue
                if in_code_block or (not line.startswith('```')):
                    json_lines.append(line)
            response_text = '\n'.join(json_lines)

        # Parse JSON
        speakers = json.loads(response_text)

        # Validate structure
        if not isinstance(speakers, list):
            print(f"[AGENDA] Gemini returned non-list: {type(speakers)}")
            return []

        # Validate each speaker has required fields
        valid_speakers = []
        for speaker in speakers:
            if isinstance(speaker, dict) and 'name' in speaker and 'role' in speaker:
                if 'confidence' not in speaker:
                    speaker['confidence'] = 'high'
                valid_speakers.append(speaker)

        return valid_speakers

    except requests.exceptions.RequestException as e:
        print(f"[AGENDA] Gemini API request error: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"[AGENDA] Failed to parse Gemini JSON response: {e}")
        print(f"[AGENDA] Response was: {response_text[:500]}")
        return []
    except Exception as e:
        print(f"[AGENDA] Gemini extraction error: {e}")
        return []


def _extract_members_present(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """
    Extract members from "Members Present" or "In Attendance" section.

    This is the most reliable source as it lists who actually attended the meeting.
    """
    members = []

    # Look for headings that indicate member attendance
    # Common patterns: "Members Present", "Present", "In Attendance", "Attending Members"
    heading_patterns = [
        r'members?\s+present',
        r'present\s*:',
        r'in\s+attendance',
        r'attending\s+members?',
        r'those\s+present'
    ]

    for pattern in heading_patterns:
        # Search for headings (h1-h6, strong, b tags, or lines ending with colon)
        for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b', 'p', 'div']):
            text = element.get_text().strip()

            if re.search(pattern, text, re.IGNORECASE):
                print(f"[AGENDA] Found 'Members Present' section: '{text}'")

                # Get the next siblings or parent's next siblings to find the member list
                current = element

                # Try to find the list/content that follows this heading
                # Strategy 1: Look for next sibling elements
                for sibling in element.find_next_siblings():
                    # Stop if we hit another heading
                    if sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        break

                    # Extract from lists
                    if sibling.name in ['ul', 'ol']:
                        for li in sibling.find_all('li'):
                            member = _parse_member_name(li.get_text())
                            if member:
                                members.append(member)

                    # Extract from paragraphs or divs
                    elif sibling.name in ['p', 'div']:
                        text_content = sibling.get_text()
                        # First try splitting by common delimiters
                        for line in re.split(r'[,;\n]', text_content):
                            member = _parse_member_name(line)
                            if member:
                                members.append(member)

                        # If no members found, try splitting by role keywords (for concatenated text)
                        if not members:
                            # Split before each title keyword
                            parts = re.split(r'(?=Councillor|Mayor|Chief Administrative Officer|Representative)', text_content)
                            for part in parts:
                                member = _parse_member_name(part.strip())
                                if member:
                                    members.append(member)

                    # Extract from tables
                    elif sibling.name == 'table':
                        for cell in sibling.find_all(['td', 'th']):
                            member = _parse_member_name(cell.get_text())
                            if member:
                                members.append(member)

                # Strategy 2: Look within the same element (text after the heading)
                if not members:
                    # Check if the heading element contains the list
                    parent = element.parent
                    if parent:
                        parent_text = parent.get_text()
                        # Split by newlines and parse each line
                        for line in parent_text.split('\n'):
                            if re.search(pattern, line, re.IGNORECASE):
                                continue  # Skip the heading line itself
                            member = _parse_member_name(line)
                            if member:
                                members.append(member)

                        # If still no members, try splitting by role keywords (for concatenated text)
                        if not members:
                            parts = re.split(r'(?=Councillor|Mayor|Chief Administrative Officer|Representative)', parent_text)
                            for part in parts:
                                if re.search(pattern, part, re.IGNORECASE):
                                    continue  # Skip the heading line itself
                                member = _parse_member_name(part.strip())
                                if member:
                                    members.append(member)

                # If we found members, break out of the pattern loop
                if members:
                    break

        # If we found members, break out of the outer pattern loop
        if members:
            break

    return _deduplicate_speakers(members)


def _parse_member_name(text: str) -> Optional[Dict[str, str]]:
    """
    Parse a line of text to extract a council member's name and role.

    Returns a speaker dict or None if no valid member found.
    """
    text = text.strip()

    # Skip empty lines
    if not text or len(text) < 3:
        return None

    # Pattern 1: "Councillor FirstName LastName" or "Mayor FirstName LastName"
    # Updated to handle abbreviated first names (e.g., "M. Atkinson") and full names
    councillor_match = re.match(
        r'^\s*(Councillor|Mayor|Cllr\.?|Alderman)\s+([A-Z]\.?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        text,
        re.IGNORECASE
    )

    if councillor_match:
        role = councillor_match.group(1).strip()
        name = councillor_match.group(2).strip()

        # Capitalize role properly
        if role.lower().startswith('cllr'):
            role = 'Councillor'
        else:
            role = role.capitalize()

        return {
            'name': name,
            'role': role,
            'confidence': 'high'
        }

    # Pattern 2: "Chief Administrative Officer" or other admin titles
    admin_match = re.match(
        r'^\s*(Chief Administrative Officer|CAO|City Manager|City Clerk)(?:\s+Designate)?\s+([A-Z]\.?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        text,
        re.IGNORECASE
    )

    if admin_match:
        role = admin_match.group(1).strip()
        name = admin_match.group(2).strip()

        return {
            'name': name,
            'role': role.title(),
            'confidence': 'high'
        }

    # Pattern 3: Representative or other roles
    rep_match = re.match(
        r'^\s*([A-Za-z\s]+)\s+Representative,?\s+([A-Z]\.?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
        text,
        re.IGNORECASE
    )

    if rep_match:
        role = rep_match.group(1).strip()
        name = rep_match.group(2).strip()

        return {
            'name': name,
            'role': f'{role.title()} Representative',
            'confidence': 'high'
        }

    # Pattern 4: Just a name with initial and last name (e.g., "M. Atkinson")
    name_with_initial_match = re.match(r'^([A-Z]\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*$', text)

    if name_with_initial_match:
        name = name_with_initial_match.group(1).strip()

        # Validate it's not a common non-name phrase
        skip_phrases = ['members present', 'in attendance', 'present', 'absent',
                       'regrets', 'also present', 'administration', 'staff', 'ex officio']

        if any(phrase in name.lower() for phrase in skip_phrases):
            return None

        # If it's just "FirstName LastName" without a title, assume Councillor
        return {
            'name': name,
            'role': 'Councillor',
            'confidence': 'high'
        }

    # Pattern 5: Full name (e.g., "John Smith")
    name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*$', text)

    if name_match:
        name = name_match.group(1).strip()

        # Validate it's not a common non-name phrase
        skip_phrases = ['members present', 'in attendance', 'present', 'absent',
                       'regrets', 'also present', 'administration', 'staff', 'ex officio']

        if any(phrase in name.lower() for phrase in skip_phrases):
            return None

        # If it's just "FirstName LastName" without a title, assume Councillor
        return {
            'name': name,
            'role': 'Councillor',
            'confidence': 'high'
        }

    return None


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
