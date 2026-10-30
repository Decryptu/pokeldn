"""Private logs (pokeldn.app.redact): lines a run printed, with what identifies the player masked and
what a report needs kept."""
import pytest

from pokeldn.app.redact import Redactor


@pytest.mark.parametrize("line,shown", [
    # Legends Z-A host, the console's offer: the player's name as handler, the program's as trainer.
    ("[za-host] the console offers {'species': 133, 'nickname': 'Eevee', 'ht_name': 'Brendan', 'ot_name': 'PKLDN', 'level': 20}",
     "[za-host] the console offers {'species': 133, 'nickname': '***', 'ht_name': '***', 'ot_name': 'PKLDN', 'level': 20}"),
    ("[    0.0s] Host identity: OT='POKELDN', TID=0x8822, SID=0x47ed",
     "[    0.0s] Host identity: OT='POKELDN', TID=***, SID=***"),
    ("I (640) wifi:mode : sta (8c:94:df:58:cd:b8)", "I (640) wifi:mode : sta (8c:94:df:**:**:**)"),
    ('  File "/Users/someone/pokeldn/bin/frlg_trade_host.py", line 212, in <module>',
     '  File "~/pokeldn/bin/frlg_trade_host.py", line 212, in <module>'),
    (r"  File C:\Users\Someone\pokeldn\bin\sv_host.py", r"  File ~\pokeldn\bin\sv_host.py"),
    ("PermissionError: [Errno 1] Operation not permitted: '/var/mobile/Containers/Data/Application/21D36C53-99BB-41E3-9D23-2CD1DA39E48A'",
     "PermissionError: [Errno 1] Operation not permitted: '<app>'"),
    ("[   78.8s] Received: PIKACHU (#25)", "[   78.8s] Received: PIKACHU (#25)"),
    # Legends Z-A joiner, the seat's participants as Python prints them.
    ("[za]   participant 0: ip=169.254.45.1 mac=48f1eb209b22 name=b'Brendan'",
     "[za]   participant 0: ip=169.254.45.1 mac=48f1eb****** name=b'***'"),
    ("[za]   participant 1: ip=169.254.45.2 mac=021132547698 name=b'pokeldn'",
     "[za]   participant 1: ip=169.254.45.2 mac=021132****** name=b'pokeldn'"),
    ("    SEND_HELD_KEYS w1=0xaa11 x1", "    SEND_HELD_KEYS w1=0xaa11 x1"),
    ("[    1.9s] Hosting. Waiting for the console to join (ssid=8d31b205..., channel 11).",
     "[    1.9s] Hosting. Waiting for the console to join (ssid=8d31b205..., channel 11)."),
])
def test_a_line_shows_what_a_report_needs_and_masks_the_player(line, shown):
    assert Redactor()(line) == shown


def test_a_name_seen_once_is_masked_in_later_lines_as_a_whole_word():
    redact = Redactor(["Sacha"])
    redact("{'ot_name': 'Brendan'}")
    assert redact("Trade with Brendan complete; Sacha left; Crash Brendanesque") == \
        "Trade with *** complete; *** left; Crash Brendanesque"


def test_a_nickname_is_masked_where_it_stands_and_nowhere_else():
    redact = Redactor()
    redact("{'nickname': 'Eevee'}")
    assert redact("Received: Eevee (#133)") == "Received: Eevee (#133)"


def test_every_games_own_trainer_name_is_masked():
    """A trainer per game (docs/gui.md): a run presents its game's name, which the log masks too."""
    from pokeldn.app.settings import Settings
    settings = Settings(ot="Ash", per_game_trainer=True, game_trainers={"sv": {"ot": "Misty"}, "za": {"tid": 5}})
    line = Redactor(settings.names())("[sv] offered to Misty, then Ash")
    assert "Misty" not in line and "Ash" not in line
    settings.per_game_trainer = False
    assert settings.names() == ["Ash"]
