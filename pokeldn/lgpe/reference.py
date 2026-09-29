"""The kind-1 identity message a Let's Go station sends, recorded from an emulated save whose trainer
is POKELDN (docs/lgpe_session.md, Kind 1). Its trainer id pair is overwritten before sending.
"""
import os

IDENTITY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "identity.bin")
