"""The trade above the reliable protocol, the same for a joiner and a host: the answer owed to a
peer's offer and to its commit, under this station's own step counter (docs/lgpe_session.md, "The
game's messages on the reliable protocol")."""
from pokeldn.ldn import reliable3
from pokeldn.lgpe import pb7

# set once the peer has offered: a run that ends abnormally after this point has left a trade half
# done, which on a retail console locks the save out of the next one for about half an hour
TRADE_IN_PROGRESS = {"offer": False, "commit": False}


def fresh_offer(args, tag="[lg]"):
    """`--fresh-pid`: write the offer under a new PID and constant beside the original and point
    `args.offer` at it, so the offer and the result message carry the same record."""
    if not getattr(args, "fresh_pid", False) or args.offer in (None, "echo"):
        return
    body = pb7.fresh(open(args.offer, "rb").read())
    path = args.offer.rsplit(".", 1)[0] + "_fresh.pb7"
    with open(path, "wb") as fh:
        fh.write(body)
    pid = int.from_bytes(pb7.decrypt(body)[pb7.OFF_PID:pb7.OFF_PID + 4], "little")
    print(f"{tag} offer: {args.offer} under pid {pid:08x}, written to {path}")
    args.offer = path


def _warn_if_mid_trade(tag="[lg]"):
    """Say plainly that the link died with a trade half done.

    A run that ends here has left the peer waiting, and a retail console answers that by refusing the
    next trade for about half an hour with no save restore available. Reading a run's end as one's
    own doing rather than checking why it ended is what made this cost a lockout once already.
    """
    if not TRADE_IN_PROGRESS["offer"]:
        return
    stage = "after the commit" if TRADE_IN_PROGRESS["commit"] else "during the offers"
    print(f"{tag} *** THE LINK ENDED MID-TRADE, {stage} *** the peer was mid-exchange when this "
          "run stopped. A console will refuse the next trade for about half an hour.")


def _send_step(state, send, kind, body):
    """Send one trade message under our next step and return it."""
    state["step"] = step = state.get("step", 1) + 1
    send(state["window"].send(pb7.build_message(kind, body, step=step)), reliable3.PROTOCOL)
    return step


def _answer_commit(args, state, msg, send, tag="[lg]"):
    """The peer's player has agreed to the trade. Agree back.

    The commit is one u32 holding 1. Both stations send one, and the peer sits on its "Attention!"
    screen with a spinner until ours arrives: that screen has no button, so nothing on its side can
    move the trade on.
    """
    if not args.offer or msg["step"] <= state.get("answered_step", 0):
        return
    state["answered_step"] = msg["step"]
    TRADE_IN_PROGRESS["commit"] = True
    step = _send_step(state, send, pb7.COMMIT_MESSAGE, msg["body"])
    print(f"{tag} offer: *** COMMITTED step {step} *** answering the peer's step {msg['step']}")


def _answer_offer(args, state, msg, send, tag="[lg]"):
    """The host has offered a Pokemon. Answer with ours, once.

    Its offer is a box structure whose checksum we can verify, so `--offer echo` returns exactly the
    bytes it sent, which is by construction a structure the game accepts: a refusal of that one is
    about the protocol rather than the contents.
    """
    if not args.offer or msg["step"] <= state.get("answered_step", 0):
        return
    if not pb7.valid(msg["body"]):
        print(f"{tag} offer: the peer's structure did not verify; not answering")
        return
    plain = pb7.decrypt(msg["body"])
    print(f"{tag} offer: the peer holds species "
          f"{int.from_bytes(plain[8:10], 'little')} "
          f"{plain[0x40:0x5A].decode('utf-16le').split(chr(0))[0]!r}")
    if args.offer == "echo":
        body = msg["body"]
    else:
        raw = open(args.offer, "rb").read()
        if len(raw) != pb7.BOX_SIZE:
            print(f"{tag} offer: {args.offer} is {len(raw)} bytes, not {pb7.BOX_SIZE}")
            return
        body = raw if pb7.valid(raw) else pb7.encrypt(raw)
    # the peer sends a fresh message under the next step every time its player changes what it is
    # offering, so an answer is owed per step rather than once per session
    state["answered_step"] = msg["step"]
    TRADE_IN_PROGRESS["offer"] = True
    step = _send_step(state, send, pb7.OFFER_MESSAGE, body)
    what = "the peer's own structure" if args.offer == "echo" else args.offer
    print(f"{tag} offer: *** SENT {len(body)} B step {step} *** {what} "
          f"(answering the peer's step {msg['step']})")
