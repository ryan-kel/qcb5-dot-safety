"""Canonical NYC DCP LION-aligned street & intersection formatting for QCB5 DOT Safety.

Standardizes raw NYPD Motor Vehicle Collisions (mixed pre-2024 spelled-out and
2024+ abbreviated ALL-CAPS), NYC DOT Signal Studies (ALL-CAPS), NYC DOT Speed
Reducer Tracking System (ALL-CAPS), and NYC DOT APS inventory labels into one
consistent NYC DCP LION / USPS-aligned Title Case convention so display labels
are legible and identical intersections never split across spelling variants.

Authoritative street/boundary references:
- NYC Department of City Planning (DCP) Bytes of the Big Apple (nycd BoroCD 405)
- NYC DCP LION / Property Address Directory (PAD) / NYC GeoSearch
"""

import re

# Exact normalized (uppercase, single-spaced) canonical overrides for known
# QCB5 street spelling variants and NYPD/DOT data typos.
_EXACT_ALIASES = {
    'DE KALB AVE': 'DeKalb Ave',
    'DE KALB AVENUE': 'DeKalb Ave',
    'DEKALB AVE': 'DeKalb Ave',
    'DEKALB AVENUE': 'DeKalb Ave',
    'MOUNT OLIVET CRES': 'Mount Olivet Cres',
    'MOUNT OLIVET CRESCENT': 'Mount Olivet Cres',
    'MT OLIVET CRES': 'Mount Olivet Cres',
    'MT OLIVET CRESCENT': 'Mount Olivet Cres',
    'MT OLIVER CRESCENT': 'Mount Olivet Cres',
    'PLEASANT VIEW ST': 'Pleasantview St',
    'PLEASANT VIEW STREET': 'Pleasantview St',
    'PLEASANTVIEW ST': 'Pleasantview St',
    'PLEASANTVIEW STREET': 'Pleasantview St',
    'SAINT FELIX AVE': 'St Felix Ave',
    'SAINT FELIX AVENUE': 'St Felix Ave',
    'ST FELIX AVE': 'St Felix Ave',
    'ST FELIX AVENUE': 'St Felix Ave',
    'SAINT NICHOLAS': 'St Nicholas Ave',
    'SAINT NICHOLAS AVE': 'St Nicholas Ave',
    'SAINT NICHOLAS AVENUE': 'St Nicholas Ave',
    'ST NICHOLAS AVE': 'St Nicholas Ave',
    'ST NICHOLAS AVENUE': 'St Nicholas Ave',
    'SAINT JOHNS RD': 'St Johns Rd',
    'SAINT JOHNS ROAD': 'St Johns Rd',
    'ST JOHNS RD': 'St Johns Rd',
    'ST JOHNS ROAD': 'St Johns Rd',
    'ROBINSON PARKWAY': 'Jackie Robinson Pkwy',
}

# Canonical NYC DCP LION / USPS street type tokens.
_STREET_TYPES = {
    'AVENUE': 'Ave',
    'AVE': 'Ave',
    'AV': 'Ave',
    'STREET': 'St',
    'STR': 'St',
    'ST': 'St',
    'ROAD': 'Rd',
    'RD': 'Rd',
    'BOULEVARD': 'Blvd',
    'BLVD': 'Blvd',
    'BLV': 'Blvd',
    'PLACE': 'Pl',
    'PL': 'Pl',
    'DRIVE': 'Dr',
    'DR': 'Dr',
    'LANE': 'Ln',
    'LN': 'Ln',
    'COURT': 'Ct',
    'CT': 'Ct',
    'PARKWAY': 'Pkwy',
    'PKWY': 'Pkwy',
    'PKY': 'Pkwy',
    'PY': 'Pkwy',
    'EXPRESSWAY': 'Expy',
    'EXPWY': 'Expy',
    'EXPY': 'Expy',
    'TURNPIKE': 'Tpke',
    'TPKE': 'Tpke',
    'TPK': 'Tpke',
    'TERRACE': 'Ter',
    'TERR': 'Ter',
    'TER': 'Ter',
    'CRESCENT': 'Cres',
    'CRES': 'Cres',
    'HIGHWAY': 'Hwy',
    'HWY': 'Hwy',
    'SQUARE': 'Sq',
    'SQ': 'Sq',
    'CIRCLE': 'Cir',
    'CIR': 'Cir',
    'ALLEY': 'Aly',
    'ALY': 'Aly',
}

_DIRECTIONALS = {
    'NORTH': 'N',
    'N': 'N',
    'SOUTH': 'S',
    'S': 'S',
    'EAST': 'E',
    'E': 'E',
    'WEST': 'W',
    'W': 'W',
}

_PRESERVE_UPPER = {
    'LIRR', 'LIE', 'BQE', 'CDR', '(CDR)', 'SR', 'WB', 'EB', 'NB', 'SB',
    'NYC', 'MTA', 'DOT', 'QCB5', 'APS', 'IBX', 'JFK', 'FDR', 'MLK', 'NYCHA',
    'P.S.', 'I.S.', 'M.S.', 'H.S.', 'J.H.S.', 'II', 'III', 'IV',
}

_MIXED_CASE_TOKENS = {
    'DEKALB': 'DeKalb',
    'MCDONALD': 'McDonald',
    'MCGUINNESS': 'McGuinness',
    "O'BRIEN": "O'Brien",
    'VANWYCK': 'Van Wyck',
}

_SAINT_FOLLOWERS = {
    'NICHOLAS', 'FELIX', 'JOHNS', 'JOHN', 'JAMES', 'MARKS', 'PAUL', 'PETERS',
    'ANN', 'ANNS', 'EDWARD', 'EDWARDS', 'RAYMOND', 'LAWRENCE', 'MICHAEL',
}

_ORDINAL_RE = re.compile(r'^(\d+)(ST|ND|RD|TH)$', re.IGNORECASE)


def clean_whitespace(text):
    """Trim and collapse runs of whitespace to single spaces."""
    if text is None:
        return ''
    s = str(text)
    if s.lower() == 'nan':
        return ''
    return ' '.join(s.strip().split())


def _format_token(tok, idx, tokens):
    up = tok.upper()
    if up in _PRESERVE_UPPER:
        return up
    if up in _MIXED_CASE_TOKENS:
        return _MIXED_CASE_TOKENS[up]

    # Ordinals like 1ST, 2ND, 3RD, 69TH -> 1st, 2nd, 3rd, 69th
    m = _ORDINAL_RE.match(up)
    if m:
        return f'{m.group(1)}{m.group(2).lower()}'

    # Leading Saint / St before a saint's name (e.g. St Nicholas Ave, St Felix Ave)
    if idx == 0 and up in ('SAINT', 'ST', 'ST.') and len(tokens) > 1 and tokens[1].upper() in _SAINT_FOLLOWERS:
        return 'St'

    # Leading Mount / Mt before a place name
    if idx == 0 and up in ('MT', 'MT.'):
        return 'Mount'

    # Street types (not at position 0, so "St Nicholas" isn't mishandled)
    if idx > 0 and up in _STREET_TYPES:
        return _STREET_TYPES[up]

    # Compass directionals at start (e.g. E 16th St) or end after street type / SR
    if up in _DIRECTIONALS:
        if idx == 0 and len(tokens) > 1:
            return _DIRECTIONALS[up]
        if idx == len(tokens) - 1 and idx > 0:
            prev_up = tokens[idx - 1].upper()
            if prev_up in _STREET_TYPES or prev_up in ('SR', 'EXIT', 'RAMP'):
                return _DIRECTIONALS[up]

    # Handle hyphenated words cleanly (e.g. FLATBUSH-NOSTRAND)
    if '-' in tok:
        return '-'.join(p.capitalize() if p.upper() not in _PRESERVE_UPPER else p.upper() for p in tok.split('-'))

    return tok.capitalize()


def format_nyc_street(name):
    """Format a street or corridor name in canonical NYC DCP LION-aligned Title Case."""
    s = clean_whitespace(name)
    if not s:
        return ''
    up = s.upper()
    if up in _EXACT_ALIASES:
        return _EXACT_ALIASES[up]

    tokens = s.split(' ')
    out = [_format_token(tok, i, tokens) for i, tok in enumerate(tokens)]
    return ' '.join(out)


def format_nyc_intersection(street_a, street_b, sort_pair=True):
    """Format an intersection cleanly; optionally sort streets canonically to prevent A&B vs B&A splits."""
    a = format_nyc_street(street_a)
    b = format_nyc_street(street_b)
    parts = [p for p in (a, b) if p]
    if not parts:
        return ''
    if len(parts) == 1:
        return parts[0]
    if sort_pair:
        parts = sorted(parts)
    return f'{parts[0]} & {parts[1]}'


def format_aps_location(loc):
    """Format DOT APS location strings (e.g. '80 Street and  68 Road' -> '80 St & 68 Rd')."""
    s = clean_whitespace(loc)
    if not s:
        return ''
    parts = re.split(r'\s+(?:and|with|&|at)\s+', s, flags=re.IGNORECASE)
    formatted = [format_nyc_street(p) for p in parts if clean_whitespace(p)]
    return ' & '.join(formatted) if formatted else format_nyc_street(s)


def format_school_name(name):
    """Format ALL-CAPS DOT school names while preserving P.S./I.S./M.S./H.S. prefixes."""
    s = clean_whitespace(name)
    if not s:
        return ''
    # Only re-case if mostly ALL-CAPS (preserve already mixed-case school names)
    letters = [c for c in s if c.isalpha()]
    if not letters or not all(c.isupper() for c in letters):
        return s
    out = []
    for tok in s.split(' '):
        up = tok.upper()
        if up in _PRESERVE_UPPER or re.match(r'^(?:P\.S\.|I\.S\.|M\.S\.|H\.S\.|J\.H\.S\.)$', up):
            out.append(up)
        elif up in ('OF', 'AND', 'THE', 'FOR', 'IN', 'AT') and out:
            out.append(up.lower())
        else:
            out.append(tok.capitalize())
    return ' '.join(out)
