from __future__ import annotations
import json, re, time, urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup
from urllib import robotparser

# ---- Config ----
INPUT_PATH   = "companies.txt"       # Input file with company names and URLs
OUTPUT_PATH  = "founders.json"       # Output file for extracted founder names
TIMEOUT_SECS = 10                    # HTTP request timeout
SLEEP_SECS   = 0.8                   # Sleep time between requests
MAX_PAGES    = 6                     # Maximum pages to scrape per company
USER_AGENT   = "FounderFinderBot (+https://example.org; contact: tool-user)"

# Paths to search which are likely to mention founders
DEFAULT_PATHS = [
    "/", "/about", "/about-us", "/company", "/our-story", "/story",
    "/team", "/leadership", "/management", "/people", "/founders",
    "/press", "/news"
]

# ---- Name validation ----
NAME_TOKEN_RE = re.compile(r"^[A-Z][a-z]+(?:[-'][A-Za-z]+)?$")

# Tokens that are unlikely to be part of a person's name
NON_NAME_TOKENS = {
  "Chief","Executive","Officer","CEO","COO","CTO","CFO","Founder",
  "Co-Founder","Co-Founder","CoFounder",
  "Managing","Partner","Director","Senior","Former","Press","News","Team",
  "About","Our","The","Board","Early","Stage","Read","More","Join","Us","If",
  "Use","Code","Mission","Company","Science","Engineer","Data","Head","VP",
  "Vice","President","Investor","Advisor","Lead","Principal","Growth","Marketing"
}

# Makes sure that the extracted text is a person's name
def is_plausible_person_name(text: str) -> bool:
    parts = [p for p in text.strip().split() if p]
    if not (2 <= len(parts) <= 4): return False
    for p in parts:
        if p in NON_NAME_TOKENS: return False
        if not NAME_TOKEN_RE.match(p): return False
    return True

# Possible patterns associated with founders names
FOUNDER_CUE = re.compile(r"(?i)\b(co[-\s–]?founder|founder|founded by)\b")
FOUNDED_BY_SENT = re.compile(
    r"(?is)\bfounded by\b\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}(?:\s*(?:,|and|&)\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})*)"
)
FOUNDER_NAME_RIGHT = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b\s*[,–—\-()]*\s*\b(co[-\s–]?founder|founder)\b", re.I
)
FOUNDER_NAME_LEFT  = re.compile(
    r"\b(co[-\s–]?founder|founder)\b\s*[,–—\-()]*\s*\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", re.I
)

# ---- Fetch utilities ----

# Normalize an URL to its canonical base (scheme + domain). If scheme is missing, assume https://.
def canonical_base(url: str) -> str:
    p = urllib.parse.urlparse(url)
    if not p.scheme:
        url = "https://" + url
        p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"

# Build URLs to fetch from based on the base URL and common paths
def build_candidate_urls(base_url: str) -> List[str]:
    seen, out = set(), []
    for path in DEFAULT_PATHS:
        u = urllib.parse.urljoin(base_url, path)
        if u not in seen:
            seen.add(u); out.append(u)
    return out

# Check if fetching the URL is allowed by robots.txt
def allowed_by_robots(base_url: str, url: str, timeout: int) -> bool:
    try:
        rp = robotparser.RobotFileParser()
        rp.set_url(urllib.parse.urljoin(base_url, "/robots.txt"))
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True

# Fetch the URL and return the HTML text if status is 200
def fetch(url: str, timeout: int) -> Optional[str]:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept":"text/html,application/xhtml+xml"}, timeout=timeout)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type",""):
            return r.text
    except requests.RequestException:
        return None
    return None

# Strip non content tags and strip whitespaces for clean regex scanning.
def text_from_soup(soup: BeautifulSoup) -> str:
    for tag in soup(["script","style","noscript","svg"]): tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())

# ---- Extraction ----

# Extract founder names from sentences
def extract_from_founded_by(text: str) -> Set[str]:
    out = set()
    for m in FOUNDED_BY_SENT.finditer(text):
        blob = m.group(1)
        for p in re.split(r"\s*(?:,|and|&)\s*", blob):
            cand = p.strip()
            if is_plausible_person_name(cand):
                out.add(cand)
    return out

# Find containers that contain founder cues and extract text from them
def container_texts_with_cues(soup: BeautifulSoup) -> List[str]:
    chunks = []
    for node in soup.find_all(string=FOUNDER_CUE):
        el, depth = node.parent, 0
        while el and el.parent and len(el.get_text(strip=True)) < 2500 and depth < 4:
            el, depth = el.parent, depth+1
        if el:
            chunks.append(" ".join(el.get_text(" ", strip=True).split()))
    return chunks

# From each container with founder cues, only extract names using patterns
def extract_from_cue_containers(soup: BeautifulSoup) -> Set[str]:
    out = set()
    for chunk in container_texts_with_cues(soup):
        for m in FOUNDER_NAME_RIGHT.finditer(chunk):
            nm = m.group(1).strip()
            if is_plausible_person_name(nm): out.add(nm)
        for m in FOUNDER_NAME_LEFT.finditer(chunk):
            nm = m.group(2).strip()
            if is_plausible_person_name(nm): out.add(nm)
    return out

# Extract founder names from the HTML content of the page
def extract_founders_from_html(html: str) -> Set[str]:
    soup = BeautifulSoup(html, "lxml")
    text = text_from_soup(soup)
    founders = set()
    founders.update(extract_from_founded_by(text))
    founders.update(extract_from_cue_containers(soup))
    return founders

# ---- Main flow ----
@dataclass
class Company:
    name: str
    url: Optional[str] = None
    founders: Set[str] = field(default_factory=set)

# Parse a line like "Company Name (https://domain.com)" into name and URL
def parse_company_line(line: str) -> Tuple[str, Optional[str]]:
    line = line.strip()
    if not line: return "", None
    m = re.match(r"^(.*?)(?:\s*\((https?://[^)]+)\))?$", line)
    if m: return m.group(1).strip(), (m.group(2).strip() if m.group(2) else None)
    return line, None

# Read companies from the input file
def read_companies(path: str) -> List[Company]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln: continue
            name, url = parse_company_line(ln)
            if name: items.append(Company(name=name, url=url))
    return items

# Process a single company by fetching pages and extracting founders
def process_company(comp: Company, timeout: int, sleep: float, max_pages: int) -> Company:
    if not comp.url:
        print(f"=== {comp.name}: no URL provided; skipping")
        return comp
    base = canonical_base(comp.url)
    print(f"\n=== Processing: {comp.name} — {base}")

    tried = 0
    for url in build_candidate_urls(base):
        if tried >= max_pages: break
        tried += 1
        if not allowed_by_robots(base, url, timeout):
            print(f"  - SKIP (robots): {url}")
            continue
        print(f"  - Fetching [{tried}/{max_pages}]: {url}")
        html = fetch(url, timeout)
        if not html:
            print("    (no HTML or non-200)")
            continue
        names = extract_founders_from_html(html)
        if names:
            print(f"    -> Found: {sorted(names)}")
        comp.founders.update(names)
        time.sleep(sleep)

    print(f"=> Final founders for {comp.name}: {sorted(comp.founders) if comp.founders else []}")
    return comp

def main():
    print("Founder Finder")
    companies = read_companies(INPUT_PATH)
    print(f"Loaded {len(companies)} company(ies) from {INPUT_PATH}")

    results: Dict[str, List[str]] = {}
    for comp in companies:
        comp = process_company(comp, timeout=TIMEOUT_SECS, sleep=SLEEP_SECS, max_pages=MAX_PAGES)
        results[comp.name] = sorted(comp.founders)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
