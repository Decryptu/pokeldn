"""Online trade, independent of any game: finding a partner by game and code through public Nostr
relays, and the encrypted channel two launchers trade over (docs/online.md).

Belongs here: the relay client, the event signature, matching and the channel. Nothing here knows a
game's record format; a launcher hands records in and takes them out as bytes.
"""
