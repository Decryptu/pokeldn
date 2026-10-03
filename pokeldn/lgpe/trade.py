"""The trade above the reliable protocol, the same for a joiner and a host: the answer owed to a
peer's offer and to its commit, under this station's own step counter (docs/lgpe_session.md, "The
game's messages on the reliable protocol")."""
from pathlib import Path
from pokeldn.ldn import reliable3, show_done
from pokeldn.app import screen
from pokeldn.lgpe import pb7

# Set once the peer has offered: a run ending after this locks the retail save out of the next trade
# for 600 s of play.
TRADE_IN_PROGRESS = {"offer": False, "commit": False}

# Giving one of these for an ordinary Pokemon, the giver's kind 3 carrying 2 closes the trade
# (0x838660; docs/lgpe_session.md).
SECOND_COMMIT_SPECIES = frozenset({144, 145, 146, 150, 151, 808, 809})


def fresh_offer(args, tag="[lg]"):
    """`--fresh-pid`: write the offer under a new PID and constant beside the original and point
    `args.offer` at it, so the offer and the result message carry the same record."""
    if not getattr(args, "fresh_pid", False) or args.offer in (None, "echo"):
        return
    body = pb7.fresh(Path(args.offer).read_bytes())
    path = args.offer.rsplit(".", 1)[0] + "_fresh.pb7"
    with open(path, "wb") as fh:
        fh.write(body)
    pid = int.from_bytes(pb7.decrypt(body)[pb7.OFF_PID:pb7.OFF_PID + 4], "little")
    print(f"{tag} offer: {args.offer} under pid {pid:08x}, written to {path}")
    args.offer = path


def show_offer(path):
    """The board's screen shows the record a --offer file holds; 'echo' has none of its own."""
    if path and path != "echo":
        screen.offer("lgpe", Path(path).read_bytes())


def _warn_if_mid_trade(tag="[lg]"):
    """A trade left half done locks the retail save out of the next trade for 600 s of play."""
    if not TRADE_IN_PROGRESS["offer"]:
        return
    stage = "after the commit" if TRADE_IN_PROGRESS["commit"] else "during the offers"
    print(f"{tag} *** THE LINK ENDED MID-TRADE, {stage} *** the peer was mid-exchange when this "
          "run stopped. A console will refuse the next trade for 600 s of play.")


def _send_step(state, send, kind, body):
    state["step"] = step = state.get("step", 1) + 1
    send(state["window"].send(pb7.build_message(kind, body, step=step)), reliable3.PROTOCOL)
    return step


def _note_result(tag="[lg]", state=None):
    """The peer's kind 4: the trade has gone through on its side. The first copy after a commit
    ends the trade; a republished copy changes nothing. With `state`, the commit is this station's
    own, not the process-wide flag."""
    if not (state.pop("committed", False) if state is not None else TRADE_IN_PROGRESS["commit"]):
        return False
    TRADE_IN_PROGRESS["offer"] = TRADE_IN_PROGRESS["commit"] = False
    if state is not None:
        state["mid_trade"] = False
    show_done()
    screen.received("lgpe", (state or {}).get("peer_offer"))
    print(f"{tag} game: *** THE RESULT *** the trade has gone through on the console")
    return True


def _answer_commit(args, state, msg, send, tag="[lg]", kind=pb7.COMMIT_MESSAGE):
    """Agree back: the peer waits on a spinner with no button until our commit arrives."""
    if not args.offer or msg["step"] <= state.get("answered_step", 0):
        return
    state["answered_step"] = msg["step"]
    state["committed"] = TRADE_IN_PROGRESS["commit"] = True
    step = _send_step(state, send, kind, msg["body"])
    print(f"{tag} offer: *** COMMITTED step {step} *** answering the peer's step {msg['step']}")
    # A console host giving an ordinary Pokemon for one of these never sends the 2.
    if (msg["body"][:4] == b"\1\0\0\0" and not state.get("sent_second_commit")
            and SECOND_COMMIT_SPECIES & set(state.get("offer_species", ()))):
        state["sent_second_commit"] = True
        step = _send_step(state, send, kind, b"\2\0\0\0")
        print(f"{tag} offer: *** COMMITTED 2 step {step} *** a special species is in the trade")


def answer_console(args, state, msg, send, tag="[lg]"):
    """A joiner's answer to one game message of the console host. Trade r, from 0, offers on kind
    2 + 2r, commits on 3 + 2r and ends on 4 + 2r, which is trade r + 1's offer channel: its first
    message is answered with the next record of `args.offers` (docs/lgpe_session.md). After the
    last record nothing is answered."""
    r = state.setdefault("round", 0)
    kind = msg["kind"]
    if kind == pb7.OFFER_MESSAGE + 2 * r:
        _answer_offer(args, state, msg, send, tag, kind=kind)
    elif kind == pb7.COMMIT_MESSAGE + 2 * r:
        _answer_commit(args, state, msg, send, tag, kind=kind)
    elif kind == pb7.RESULT_MESSAGE + 2 * r and _note_result(tag, state):
        queue = getattr(args, "offers", None) or [args.offer]
        if r + 1 >= len(queue):
            print(f"{tag} game: trade {r + 1} was the last queued; a further trade is not answered")
            return
        from pokeldn.pokemon import trade_path
        state["round"] = r + 1
        state.pop("sent_second_commit", None)
        state.setdefault("received", getattr(args, "received", None))
        args.offer = queue[r + 1]
        show_offer(args.offer)
        args.received = trade_path(state["received"], r + 2)
        print(f"{tag} game: trade {r + 2} offers on kind {kind}, commits on kind {kind + 1}")
        _answer_offer(args, state, msg, send, tag, kind=kind)


def _answer_offer(args, state, msg, send, tag="[lg]", kind=pb7.OFFER_MESSAGE):
    """Answer the host's offer with ours, once; `--offer echo` returns its own bytes."""
    if not args.offer or msg["step"] <= state.get("answered_step", 0):
        return
    if not pb7.valid(msg["body"]):
        print(f"{tag} offer: the peer's structure did not verify; not answering")
        return
    if getattr(args, "received", None):
        from pokeldn.pokemon import save_received
        save_received("lgpe", args.received, msg["body"])
    state["peer_offer"] = msg["body"]
    plain = pb7.decrypt(msg["body"])
    peer_species = int.from_bytes(plain[8:10], "little")
    print(f"{tag} offer: the peer holds species "
          f"{peer_species} "
          f"{plain[0x40:0x5A].decode('utf-16le').split(chr(0))[0]!r}")
    if args.offer == "echo":
        body = msg["body"]
    else:
        raw = Path(args.offer).read_bytes()
        if len(raw) != pb7.BOX_SIZE:
            print(f"{tag} offer: {args.offer} is {len(raw)} bytes, not {pb7.BOX_SIZE}")
            return
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
    state["offer_species"] = (int.from_bytes(pb7.decrypt(body)[8:10], "little"), peer_species)
    # The peer sends a fresh step each time its player changes the offer; each is owed an answer.
    state["answered_step"] = msg["step"]
    state["mid_trade"] = TRADE_IN_PROGRESS["offer"] = True
    step = _send_step(state, send, kind, body)
    what = "the peer's own structure" if args.offer == "echo" else args.offer
    print(f"{tag} offer: *** SENT {len(body)} B step {step} *** {what} "
          f"(answering the peer's step {msg['step']})")
