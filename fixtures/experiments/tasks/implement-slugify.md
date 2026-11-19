## Task

Implement `slugify(text: str) -> str` in `slugify.py` so it turns free-form text into a URL-safe slug.

## Constraints

- Keep the function in `slugify.py`
- Do not add external dependencies
- Lowercase ASCII letters and digits only; words separated by a single hyphen
- Collapse runs of whitespace and punctuation into one hyphen
- Strip leading and trailing hyphens

## Acceptance Criteria

1. `slugify("Hello World")` returns `"hello-world"`
2. `slugify("  Foo   Bar  ")` returns `"foo-bar"`
3. `slugify("Hello, World!")` returns `"hello-world"`
4. `slugify("Already-Slug")` returns `"already-slug"`
5. `slugify("")` returns `""`
