"""`python -m larb`: the window without arguments, the command-line program with them."""

import sys

if len(sys.argv) > 1:
    from larb.cli import main
else:
    from larb.gui import main

sys.exit(main())
