#!/usr/bin/env python3
"""
Agenda Parser for Calgary Council Stream Recorder.
Extracts expected speaker names from meeting agenda HTML pages using Gemini AI.
"""

import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import json


def extract_speakers(
    agenda_url: Optional[str], timeout: int = 10
) -> List[Dict[str, str]]:
    """
    Extract speaker names from a meeting agenda HTML page using Gemini AI.

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
        # SSL verification enabled for security
        response = requests.get(agenda_url, timeout=timeout)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Use Gemini AI extraction
        try:
            from config import GEMINI_API_KEY, GEMINI_MODEL

            if GEMINI_API_KEY:
                print("[AGENDA] Attempting Gemini AI extraction")
                model = GEMINI_MODEL if 'GEMINI_MODEL' in dir() else "gemini-2.5-flash"
                speakers = _extract_speakers_with_gemini(soup, GEMINI_API_KEY, model)
                if speakers:
                    print(f"[AGENDA] Gemini AI found {len(speakers)} speakers")
                    return speakers
                else:
                    print("[AGENDA] WARNING: Gemini AI returned no speakers")
                    return []
            else:
                print("[AGENDA] ERROR: No Gemini API key configured")
                return []
        except ImportError:
            print("[AGENDA] ERROR: Config module not available")
            return []
        except Exception as e:
            print(f"[AGENDA] ERROR: Gemini extraction failed: {e}")
            return []

    except requests.Timeout:
        print(f"[AGENDA] ERROR: Timeout fetching agenda from {agenda_url}")
        return []
    except requests.RequestException as e:
        print(f"[AGENDA] ERROR: Failed to fetch agenda: {e}")
        return []
    except Exception as e:
        print(f"[AGENDA] ERROR: Failed to parse agenda: {e}")
        return []


def _extract_speakers_with_gemini(
    soup: BeautifulSoup, api_key: str, model: str = "gemini-2.5-flash"
) -> List[Dict[str, str]]:
    """
    Use Gemini AI to extract speakers from HTML content via REST API.

    Args:
        soup: BeautifulSoup parsed HTML
        api_key: Gemini API key
        model: Gemini model to use (default: gemini-2.5-flash)

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

        # Use REST API directly with configured model
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()

        # Extract text from response
        if "candidates" in result and len(result["candidates"]) > 0:
            candidate = result["candidates"][0]
            if "content" in candidate and "parts" in candidate["content"]:
                response_text = candidate["content"]["parts"][0]["text"].strip()
            else:
                print("[AGENDA] Unexpected Gemini response structure")
                return []
        else:
            print("[AGENDA] No candidates in Gemini response")
            return []

        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_code_block = False
            for line in lines:
                if line.startswith("```"):
                    in_code_block = not in_code_block
                    continue
                if in_code_block or (not line.startswith("```")):
                    json_lines.append(line)
            response_text = "\n".join(json_lines)

        # Parse JSON
        speakers = json.loads(response_text)

        # Validate structure
        if not isinstance(speakers, list):
            print(f"[AGENDA] Gemini returned non-list: {type(speakers)}")
            return []

        # Validate each speaker has required fields
        valid_speakers = []
        for speaker in speakers:
            if isinstance(speaker, dict) and "name" in speaker and "role" in speaker:
                if "confidence" not in speaker:
                    speaker["confidence"] = "high"
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
