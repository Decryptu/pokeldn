"""bin/swsh_connect.py --trade-back against bin/swsh_host.py on simulated boards: the joiner's second
trade returns, byte for byte, the record the host sent in the first (pokeldn/trade_back.py). Either
side's --hold-after-trade then ends the run through its departure messages, well before --hold."""
import contextlib
import threading
import time

import pytest


@pytest.mark.parametrize("holder", ["host", "join"])
def test_the_sword_joiner_returns_the_consoles_pokemon_in_the_next_trade(tmp_path, monkeypatch, capsys,
                                                                         holder):
    import swsh_connect
    import swsh_host
    from ldn import wlan
    from test_esp32 import KEYS
    from test_swsh_trade_payload import a_payload
    from pokeldn import gen8, pokemon as pokemon_service
    from pokeldn.ldn import esp32, esp32_sim, esp32_wlan, userspace_ip
    from pokeldn.swsh import pokemon

    monkeypatch.setenv("POKELDN_RADIO", "esp32:simulated")
    monkeypatch.setattr(pokemon_service, "prepare_file", lambda game, path, **kw: path)
    monkeypatch.setattr(pokemon_service, "prepare", lambda game, raw, **kw: gen8.decrypt(raw))
    keys_file = tmp_path / "prod.keys"
    keys_file.write_text("".join(f"{k} = {v.hex()}\n" for k, v in KEYS.items()))
    party = a_payload(count=4)
    (tmp_path / "snapshot.bin").write_bytes(party)
    for slot in range(4):
        (tmp_path / f"offer{slot}.pk8").write_bytes(party[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY])
    air = esp32_sim.Air()
    host_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    join_radio = esp32.Radio(esp32_sim.SimulatedBoard(air).host_stream())
    threads = {}

    @contextlib.asynccontextmanager
    async def factory():
        radio = join_radio if threading.current_thread() is threads.get("join") else host_radio
        esp = esp32_wlan.EspFactory(radio, port_factory=userspace_ip.userspace_port, join_timeout=5)
        try:
            yield esp
        finally:
            esp.router.close()

    hold = {side: ["--hold-after-trade", "1"] if side == holder else [] for side in ("host", "join")}
    result = {}
    threads["host"] = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--keys", str(keys_file), "--channel", "6", "--seconds", "90", "--accept-first",
         "--lead", "3", *hold["host"],
         "--snapshot", str(tmp_path / "snapshot.bin"), "--received", str(tmp_path / "host.pk8"),
         "--offer-file", str(tmp_path / "offer0.pk8"), "--offer-file", str(tmp_path / "offer1.pk8")])),
        daemon=True)
    threads["join"] = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        ["--keys", str(keys_file), "--preset", "trade", "--channels", "6", "--dwell", "0.5",
         "--hold", "90", *hold["join"], "--save-offered", str(tmp_path / "join.pk8"), "--trade-back",
         "--offer-file", str(tmp_path / "offer2.pk8")])),
        daemon=True)
    wlan.set_factory(factory)
    try:
        started = time.monotonic()
        threads["join"].start()
        threads["host"].start()
        threads["join"].join(150)
        threads["host"].join(150)
        took = time.monotonic() - started
    finally:
        wlan.set_factory(None)
        host_radio.close()
        join_radio.close()
    assert result == {"host": 0, "join": 0}
    out = capsys.readouterr().out
    if holder == "host":
        assert "1s after trade 2; closing the session" in out
        assert "START_HOST_MIGRATION: THE CONSOLE IS CLOSING ITS NETWORK" in out
    else:
        assert "leaving the seat 1s after trade 2" in out
        assert "left the seat: leave request answered, disconnection answered" in out
        assert "the console left after the trade; closing" in out
    assert took < 70, took          # --seconds and --hold are 90 s

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    # Trade 1: our first queued offer (offer2) for the host's offer0.
    assert species("host.pk8") == 96
    assert species("join.pk8") == 94
    # Trade 2: the host receives the very bytes it sent in trade 1, not offer2 again.
    sent = (tmp_path / "join.pk8").read_bytes()
    assert len(sent) == gen8.SIZE_PARTY
    assert (tmp_path / "host-2.pk8").read_bytes() == sent
