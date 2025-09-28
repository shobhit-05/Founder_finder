# Founder Finder

This small script reads `companies.txt` (one company per line with a URL in parentheses)
and writes `founders.json` mapping each company name to a list of founder names.

## Example input file
```
Airbnb (https://www.airbnb.com/)
Dropbox (https://www.dropbox.com/)
```

## Quickstart

```bash
# 1) Create a virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 2) Install all requirements
pip install -r requirements.txt

# 3) Run the code
python3 founder_finder.py
```

The script will scan a few common pages on each company’s site (e.g., `/about`, `/leadership`, `/founders`)
and extract names which have context like “Founder”, “Co‑Founder”, or “Founded by”.

## Output
`founders.json`:
```json
{
  "Airbnb": ["Brian Chesky", "Joe Gebbia", "Nathan Blecharczyk"],
  "Dropbox": ["Arash Ferdowsi", "Drew Houston"]
}
```

If no founders are found for a company, the value will be an empty array `[]`.

## Approach & Assumptions

- **Tight extraction rules:** Only accept founders from directly attached cues like "Founded by ..."
- **Company-site Only**: Retrieves information from the company's own `/about`, `/team`, `/leadership` pages.
- **Shallow & deterministic:** Limits the man number of pages to scan to 6 and conducts a best-effort `robots.txt` check.
- **Non-founders excluded:** Ignore roles like founding engineer, advisors, investors, board unless explicitly labeled Founder/Co-Founder.
- **No JS rendering:** Static HTML only to keep the script simple and fast by skipping headless rendering. 
- **Input:** Lines like `Company Name (https://domain.com)`, if company link is not present assume no match.

## Future Improvements

- **Handle JS-only pages:** Add an optional headless step if static HTML misses founders.
- **Find deeper pages:** Do a tiny `site:domain` search for “founder” / “founded by” when `/about` or `/team` is silent.
-  **Caching & Retries:** Cache pages, retry, and use small per domain parallelism for bigger lists.
- **External Verification:** Allow external source (e.g., Wikipedia, Google) to verify founders name.
- **Review mode:** Add the option to print candidates with context for human review.
- **CLI Flags:** Add flags to allow for modification in max pages scanned, HTTP timeout, and delay between requests
