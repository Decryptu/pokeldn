import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.app import paths
from pokeldn.app.runner import child

if __name__ == "__main__":
    child(sys.argv[1:])
