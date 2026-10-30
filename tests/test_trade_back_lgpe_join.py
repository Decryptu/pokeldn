"""--trade-back on the Let's Go joiner: the trade after a queued one offers the console's record back."""
from pathlib import Path
import importlib.util
import os
import struct

from pokeldn.lgpe import pb7


def _join():
    spec = importlib.util.spec_from_file_location(
        "lgpe_join", os.path.join(os.path.dirname(__file__), "..", "bin", "lgpe_join.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def box(species, ec):
    plain = bytearray(pb7.BOX_SIZE)
    struct.pack_into("<I", plain, 0, ec)
    struct.pack_into("<H", plain, 8, species)
    return pb7.encrypt(bytes(plain))


def test_the_second_trade_offers_the_console_s_first_record_back(tmp_path):
    """A console host's messages as in test_pb7's queued trades: trade 1 on kinds 2, 3, 4 and trade 2
    on 4, 5, 6. Trade 1 sends our queued record; trade 2 sends the console's trade 1 record unchanged;
    a third is not answered, as after a joiner's last queued trade."""
    mod = _join()
    queued = tmp_path / "offer0.pb7"
    queued.write_bytes(box(133, 0x1000))
    args = mod.build_parser().parse_args(["--trade-back", "--offer", str(queued)])
    args.offers = [str(queued)]
    args.offer = args.offers[0]
    mod.setup_trade_back(args)

    class Window:
        def send(self, body):
            return body

    state, sent = {"window": Window()}, []

    def console(kind, step, body):
        before = len(sent)
        mod.answer(args, state, pb7.parse_message(pb7.build_message(kind, body, step=step)),
                   lambda b, p: sent.append(pb7.parse_message(b)))
        return [(m["kind"], m["step"], m["body"]) for m in sent[before:]]

    one, two = b"\1\0\0\0", b"\2\0\0\0"
    theirs = box(64, 0xCAFE)                       # Kadabra, which evolves by trade
    assert console(2, 2, box(16, 2)) == [(2, 2, box(133, 0x1000))]
    assert console(2, 3, theirs) == [(2, 3, box(133, 0x1000))]
    assert console(3, 4, one) == [(3, 4, one)]
    assert console(3, 5, two) == [(3, 5, two)]
    assert console(4, 6, box(25, 6)) == [(4, 6, theirs)]
    assert console(5, 7, one) == [(5, 7, one)]
    assert console(5, 8, two) == [(5, 8, two)]
    assert console(6, 9, box(1, 9)) == []



def test_the_console_hosts_first_message_names_its_trainer_to_the_app(monkeypatch, capsys):
    """The recorded console kind 1, under a known trainer, as the joiner's reliable channel delivers it:
    the app is told that trainer (pokeldn.console_trainer)."""
    from pokeldn import console_trainer
    from pokeldn.ldn import reliable3
    from pokeldn.lgpe import reference
    mod = _join()
    args = mod.build_parser().parse_args([])
    console = pb7.parse_message(Path(reference.IDENTITY).read_bytes())["body"]
    console = pb7.set_trainer_id(pb7.set_trainer_name(console, "CONSOLE"), 41234, 12345)
    r = reliable3.parse(reliable3.build(pb7.build_message(pb7.FIRST_MESSAGE, console),
                                        reliable3.FIRST_SEQUENCE, reliable3.FIRST_SEQUENCE))
    mod.answer(args, {}, pb7.parse_message(r["payload"]), lambda b, p: None)
    told = [m for line in capsys.readouterr().out.splitlines() for m in [console_trainer.read(line)] if m]
    assert len(told) == 1
    assert (told[0]["game"], told[0]["source"], told[0]["ot"], told[0]["tid"], told[0]["sid"]) == \
        ("lgpe", "session", "CONSOLE", 41234, 12345)
    assert told[0]["version"] in (42, 43)
