"""tools/switch/swsh_save.py: the Sword/Shield save block layers, round-tripped and patched in place."""
import os
import swsh_save


def a_save():
    blocks = [(0x112d5141, 4, None, bytes(range(256)) * 3),     # an object block
              (0x1177c2c4, 5, 10, bytes(range(64))),             # an array of u32
              (0xf25c070e, 9, None, b"\x34\x12"),                # a u16
              (0x0d66012c, 2, None, b"")]                        # a bool
    return blocks, swsh_save.encrypt(blocks)


def test_the_two_layers_round_trip_and_the_hash_seals_the_file():
    blocks, raw = a_save()
    assert swsh_save.hash_ok(raw)
    assert swsh_save.decrypt(raw) == blocks
    assert not swsh_save.hash_ok(raw[:-1] + bytes([raw[-1] ^ 1]))


def test_a_patch_changes_only_the_bytes_named_and_reseals():
    blocks, raw = a_save()
    out = swsh_save.patch(raw, 0x112d5141, 0x100, b"\xaa\xbb\xcc\xdd")
    assert swsh_save.hash_ok(out)
    got = {b[0]: b for b in swsh_save.decrypt(out)}
    want = bytearray(blocks[0][3]); want[0x100:0x104] = b"\xaa\xbb\xcc\xdd"
    assert got[0x112d5141][3] == bytes(want)
    assert got[0x1177c2c4] == blocks[1] and got[0xf25c070e] == blocks[2]


def test_the_shield_save_on_the_share_decrypts_when_present():
    path = ("scratchpad/hgfs/Switch/save_backups/POST_245_20260919_102440/0000000000000001/0/main")
    if not os.path.exists(path):
        return
    raw = open(path, "rb").read()
    assert swsh_save.hash_ok(raw)
    by_key = {b[0]: b for b in swsh_save.decrypt(raw)}
    assert by_key[0xf25c070e][3][0xB0:0xBE].decode("utf-16-le") == "Ryujinx"
    assert len(by_key[0x112d5141][3]) == 0x17C8
