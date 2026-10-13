"""Read-only discovery against the demo tenants: same as `python -m normalization fetch`.

Responses are saved verbatim under .discovery/ (gitignored) and are never committed. Needs
DEMO_SIGNIN_API_KEY in the environment or in .env.

    python scripts/discover.py --provider all --signin-only
    python scripts/discover.py --provider prismhr --max-employees 5
"""

import sys

from normalization.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(["fetch", *sys.argv[1:]]))
