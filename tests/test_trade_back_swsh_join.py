"""bin/swsh_connect.py --trade-back against bin/swsh_host.py on simulated boards: the joiner's second
trade returns, byte for byte, the record the host sent in the first (pokeldn/trade_back.py)."""
import contextlib
import threading
import time


def test_the_sword_joiner_returns_the_consoles_pokemon_in_the_next_trade(tmp_path, monkeypatch):
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

    result = {}
    threads["host"] = threading.Thread(target=lambda: result.setdefault("host", swsh_host.main(
        ["--keys", str(keys_file), "--channel", "6", "--seconds", "50", "--accept-first",
         "--lead", "3",
         "--snapshot", str(tmp_path / "snapshot.bin"), "--received", str(tmp_path / "host.pk8"),
         "--offer-file", str(tmp_path / "offer0.pk8"), "--offer-file", str(tmp_path / "offer1.pk8")])),
        daemon=True)
    threads["join"] = threading.Thread(target=lambda: result.setdefault("join", swsh_connect.main(
        ["--keys", str(keys_file), "--preset", "trade", "--channels", "6", "--dwell", "0.5",
         "--hold", "35", "--save-offered", str(tmp_path / "join.pk8"), "--trade-back",
         "--offer-file", str(tmp_path / "offer2.pk8"), "--offer-file", str(tmp_path / "offer3.pk8")])),
        daemon=True)
    wlan.set_factory(factory)
    try:
        threads["join"].start()
        time.sleep(1.5)
        threads["host"].start()
        threads["join"].join(120)
        threads["host"].join(120)
    finally:
        wlan.set_factory(None)
        host_radio.close()
        join_radio.close()
    assert result == {"host": 0, "join": 0}

    def species(name):
        return pokemon.read(pokemon.encrypt(gen8.load((tmp_path / name).read_bytes())))["species"]
    # Trade 1: our first queued offer (offer2) for the host's offer0.
    assert species("host.pk8") == 96
    assert species("join.pk8") == 94
    # Trade 2: the host receives the very bytes it sent in trade 1, not the queued offer3.
    sent = (tmp_path / "join.pk8").read_bytes()
    assert len(sent) == gen8.SIZE_PARTY
    assert (tmp_path / "host-2.pk8").read_bytes() == sent
