
import logging
import requests
from cachetools import TTLCache, cached

logger = logging.getLogger(__name__)

# Cache configuration: Max 2000 items, expires in 24 hours (86400 seconds)
terminology_cache = TTLCache(maxsize=2000, ttl=86400)

@cached(cache=terminology_cache)
def get_condition_code(text):
    """
    Searches for ICD-10 codes using the US NLM API.
    Returns a valid FHIR CodeableConcept dict.
    If the API fails or no match is found, returns a fallback dict with just the text.

    Args:
        text (str): The disease or diagnosis name to search for (e.g., "Hypertension").

    Returns:
        dict: A FHIR CodeableConcept-compatible dictionary (or part of it).
              Example success: {
                  "coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10", "display": "Essential (primary) hypertension"}],
                  "text": "Hypertension"
              }
              Example fallback: {
                  "text": "Hypertension"
              }
    """
    # Strategy 1: Exact search
    clean_text = text.strip()
    result = _search_icd10(clean_text)
    if result:
        return result

    # Strategy 2: Last word (often the noun, e.g. "High Fever" -> "Fever")
    words = clean_text.split()
    if len(words) > 1:
        last_word = words[-1]
        # Ignore short words to avoid noise
        if len(last_word) > 2:
            result = _search_icd10(last_word)
            if result:
                return result

    # Strategy 3: Longest word (e.g. "Acute Bronchitis" -> "Bronchitis")
    if len(words) > 1:
        longest_word = max(words, key=len)
        if len(longest_word) > 2 and longest_word != words[-1]: # Don't repeat Strategy 2
            result = _search_icd10(longest_word)
            if result:
                return result

    # Fallback: Just return text
    return {
        "text": clean_text
    }

def _search_icd10(term):
    """Helper to query ICD-10 API"""
    base_url = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
    try:
        response = requests.get(
            base_url,
            params={"terms": term, "sf": "code,name", "df": "code,name", "maxList": 1},
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            if len(data) > 3 and data[3]:
                first_match = data[3][0]
                return {
                    "coding": [{
                        "system": "http://hl7.org/fhir/sid/icd-10-cm",
                        "code": first_match[0],
                        "display": first_match[1]
                    }],
                    "text": term # Use the successful search term or keep original? Keeping original context is hard here, using matched term desc is safer.
                    # Actually, we should return the mapped code but maybe imply the text is related.
                    # Let's simple return the coding.
                }
    except Exception as e:
        logger.warning(f"ICD-10 search failed for '{term}': {e}")
    return None

@cached(cache=terminology_cache)
def get_loinc_code(text):
    """
    Searches for LOINC codes using the US NLM API.
    Returns a valid FHIR CodeableConcept dict.

    Args:
        text (str): The lab test name (e.g., "Hemoglobin").

    Returns:
        dict: FHIR CodeableConcept dict with valid coding or fallback text.
    """
    if not text:
        return {"text": ""}

    # Use loinc_items endpoint
    base_url = "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search"
    clean_text = text.strip()

    try:
        # Params: terms=text, sf=text,LOINC_NUM (search fields), 
        # df=LOINC_NUM,text (display fields to ensure we get code and name in response)
        # maxList=1
        response = requests.get(
            base_url,
            params={
                "terms": clean_text, 
                "sf": "text,LOINC_NUM", 
                "df": "LOINC_NUM,text", 
                "maxList": 1
            },
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        # API response format: [total_count, codes, extra_info, display_strings]
        if len(data) > 3 and data[3]:
            # Check if display strings are list of lists or flattened
            first_item = data[3][0]
            
            # Case 1: List of lists (e.g. [[code, name], ...])
            if isinstance(first_item, list) and len(first_item) >= 2:
                code = first_item[0]
                display = first_item[1]
            # Case 2: Parallel lists (codes in data[1], names in data[3])
            elif len(data) > 1 and data[1]:
                 code = data[1][0]
                 display = first_item if isinstance(first_item, str) else str(first_item)
            else:
                 # Fallback if structure is unexpected
                 return {"text": clean_text}

            return {
                "coding": [{
                    "system": "http://loinc.org",
                    "code": code,
                    "display": display
                }],
                "text": clean_text
            }

    except Exception as e:
        logger.warning(f"LOINC lookup failed for '{clean_text}': {e}")

    return {"text": clean_text}

@cached(cache=terminology_cache)
def get_rxnorm_code(text):
    """
    Searches for RxNorm codes using the NLM RxNav API.
    Returns a valid FHIR CodeableConcept dict.

    Args:
        text (str): The medication name (e.g., "Metformin").

    Returns:
        dict: FHIR CodeableConcept dict with valid coding or fallback text.
    """
    if not text:
        return {"text": ""}

    # Use drugs.json endpoint
    base_url = "https://rxnav.nlm.nih.gov/REST/drugs.json"
    clean_text = text.strip()

    try:
        # Params: name=text
        response = requests.get(
            base_url,
            params={"name": clean_text},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        # Response structure: drugGroup -> conceptGroup -> [list of concepts]
        drug_group = data.get("drugGroup", {})
        concept_groups = drug_group.get("conceptGroup", [])
        
        if concept_groups:
             # Look for the first ConceptGroup that has properties (SBD (Brand) or SCD (Clinical Drug) preferred, 
             # but often we just want any valid concept)
             # The API returns different TTY (Term Types). We'll take the first available Concept.
             for group in concept_groups:
                 if "conceptProperties" in group:
                     concepts = group["conceptProperties"]
                     if concepts:
                         # Take the first concept found
                         first_concept = concepts[0]
                         rxcui = first_concept.get("rxcui")
                         name = first_concept.get("name")
                         
                         return {
                            "coding": [{
                                "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                "code": rxcui,
                                "display": name
                            }],
                            "text": clean_text
                        }

    except Exception as e:
        logger.warning(f"RxNorm lookup failed for '{clean_text}': {e}")
        
    return {"text": clean_text}

