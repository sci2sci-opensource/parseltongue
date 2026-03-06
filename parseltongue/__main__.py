"""python -m parseltongue — route to core loader or CLI."""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "load_main":
    from parseltongue import load_main

    if len(sys.argv) < 3:
        print("Usage: python -m parseltongue load_main <path.pltg>", file=sys.stderr)
        sys.exit(1)
    load_main(sys.argv[2])
else:
    from parseltongue.cli.app import main

    main()
