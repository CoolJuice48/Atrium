# Atrium Pack Manifest Schema (pack.json)

Packs are modular curriculum bundles stored under `atrium_packs/<path>/packs/<pack_id>/`.

## pack.json

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pack_id` | string | Yes | Unique identifier (e.g. `cs-foundations`) |
| `version` | string | Yes | Semantic version (e.g. `1.0.0`) |
| `title` | string | Yes | Human-readable title |
| `description` | string | No | Optional description |
| `path_id` | string | Yes | Parent learning path (e.g. `computer_science_core`) |
| `module` | object | Yes | Module metadata |
| `module.id` | string | Yes | Module identifier |
| `module.title` | string | Yes | Module title |
| `module.order` | number | Yes | Display order |
| `module.prereqs` | string[] | No | Prerequisite module IDs |
| `allowed_licenses` | string[] | No | Default: `["PUBLIC_DOMAIN","CC0","CC BY 4.0","CC BY-SA 4.0"]` |
| `books` | object[] | Yes | List of book entries |

### Book entry

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_file` | string | Yes | Relative path under `sources/` (e.g. `intro.pdf`) |
| `title` | string | No | Default: filename stem |
| `author` | string | No | Author name |
| `source_url` | string | Yes | URL where the work can be obtained |
| `license` | object | Yes | License metadata |
| `license.type` | string | Yes | Must be in `allowed_licenses` |
| `license.url` | string | Yes | URL to license text |
| `license.proof_url` | string | Yes | URL proving the license (e.g. source page) |
| `attribution` | string | Yes | Human-readable attribution text |

## Allowed licenses (commercial distribution)

Packs must contain ONLY content under:

- `PUBLIC_DOMAIN`
- `CC0`
- `CC BY 4.0`
- `CC BY-SA 4.0`

No NC (Non-Commercial) or ND (No-Derivatives) licenses are permitted.

## Example pack.json

```json
{
  "pack_id": "cs-foundations",
  "version": "1.0.0",
  "title": "CS Foundations",
  "description": "Introduction to computer science",
  "path_id": "computer_science_core",
  "module": {
    "id": "cs-foundations",
    "title": "Foundations",
    "order": 1,
    "prereqs": []
  },
  "allowed_licenses": ["PUBLIC_DOMAIN", "CC0", "CC BY 4.0", "CC BY-SA 4.0"],
  "books": [
    {
      "source_file": "intro.pdf",
      "title": "Introduction to CS",
      "author": "Author Name",
      "source_url": "https://example.com/intro.pdf",
      "license": {
        "type": "CC BY 4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "proof_url": "https://example.com/intro.pdf"
      },
      "attribution": "Introduction to CS by Author Name, CC BY 4.0"
    }
  ]
}
```
