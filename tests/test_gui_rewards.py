"""Reward editor state reaches the launcher and its serialized RaidPoint."""
import asyncio
import struct
from types import SimpleNamespace

import pytest

pytest.importorskip("flet")

import flet as ft

from gui.views import rewards
from gui import theme as t
from gui.views.widgets import PixelActivity
from pokeldn import pokemon
from pokeldn.app.catalog import GAMES
from pokeldn.app.command import build, problems
from pokeldn.app.settings import Settings
from pokeldn.sv import raid, raid_encounter
import sv_host


@pytest.fixture
def picker(monkeypatch):
    monkeypatch.setattr(rewards, "NamePicker", lambda app, game, kind, value, on_change, **kw:
                        SimpleNamespace(control=ft.Dropdown(value=value,
                            on_select=lambda e: on_change(e.control.value))))
    monkeypatch.setattr(ft.Control, "update", lambda self: None)
    saved = []
    view = rewards.RewardPicker(None, "sv", [], saved.append)
    view.saved = saved
    return view


def select(picker, template):
    picker.templates.value = template
    picker.templates.on_select(SimpleNamespace(control=picker.templates))


def quantity(picker, text):
    picker.quantity.value = text
    picker.quantity.on_change(SimpleNamespace(control=picker.quantity))


def launch(rows):
    tool = next(t for game in GAMES for t in game.tools if t.key == "sv-raid-host")
    values = {"--raid-pokemon": {"file": "host.pk9"}, "--raid-seed": "000F34C3", "--raid-reward": rows}
    return tool, values


@pytest.mark.parametrize("template", ["training", "shards", "herba", "treasure", "balls"])
def test_a_bundle_survives_saving_and_reaches_the_scripted_console(picker, monkeypatch, tmp_path, template):
    from test_sv_raid import run_raid_host, lobby_rows
    select(picker, template)
    quantity(picker, "999")
    restored = rewards.RewardPicker(None, "sv", picker.saved[-1], lambda rows: None)
    assert restored.templates.value == template and restored.quantity.value == "999"
    tool, values = launch(restored.value)
    assert not problems(tool, values)
    parsed = sv_host.build_parser().parse_args(build(tool, values, {}, Settings()))
    bag = pokemon.SERVICE.names("sv", "bag")
    console, _ = run_raid_host(monkeypatch, tmp_path, rewards=parsed.raid_reward, bag=bag)
    first = lobby_rows(console)
    plain = raid.payload_of(first[10]["data"] + first[11]["data"])
    point = plain[raid.RAIDPOINT:]
    sent = [struct.unpack_from("<4I", point, 0xE4 + 16 * n) for n in range(45)]
    assert sent[:len(restored.value)] == [(int(row["item_id"]), 999, 0, 0) for row in restored.value]
    assert all(row == (0, 0, 0, 0) for row in sent[len(restored.value):])


@pytest.mark.parametrize("text", ["", "0", "1000", "-1", "abc", "²", "９"])
def test_invalid_bulk_quantity_blocks_launch_and_keeps_the_item_controls(picker, text):
    select(picker, "shards")
    item_rows = list(picker.rows.controls)
    quantity(picker, text)
    tool, values = launch(picker.saved[-1])
    assert problems(tool, values)
    assert picker.problem.visible
    for field in [picker.quantity, *picker.quantities]:
        field.before_update()
        assert field.height == t.CONTROL_HEIGHT and field.error is None
        assert field.border[ft.ControlState.DEFAULT].side.color == t.RED
    assert all(a is b for a, b in zip(item_rows, picker.rows.controls))
    assert all(row["quantity"] == text for row in picker.saved[-1])
    quantity(picker, "1")
    assert not problems(tool, launch(picker.saved[-1])[1])
    assert not picker.problem.visible
    assert all(f.border[ft.ControlState.DEFAULT].side.color != t.RED for f in picker.quantities)


def test_individual_edits_and_removal_keep_template_controls_in_sync(picker):
    select(picker, "herba")
    field = picker.quantities[0]
    field.value = "7"
    field.on_change(SimpleNamespace(control=field))
    assert picker.templates.value == "custom" and not picker.template_quantity_control.visible
    restored = rewards.RewardPicker(None, "sv", picker.saved[-1], lambda rows: None)
    assert restored.templates.value == "custom"
    picker._add(None)
    assert picker.templates.value == "custom"
    picker._remove(len(picker.value) - 1)
    assert picker.templates.value == "custom" and not picker.template_quantity_control.visible
    for _ in range(len(picker.value)):
        picker._remove(0)
    assert picker.templates.value == "seed" and picker.saved[-1] == []
    select(picker, "training")
    select(picker, "seed")
    tool, values = launch(picker.saved[-1])
    parsed = sv_host.build_parser().parse_args(build(tool, values, {}, Settings()))
    assert not parsed.raid_reward
    found = raid_encounter.generate(parsed.raid_seed)
    assert any(raid.raid_point(found)[0xE4:0x3B4])


@pytest.mark.parametrize("item", ["bad", "²", "", None])
def test_an_incomplete_saved_item_can_be_opened_and_corrected(picker, item):
    restored = rewards.RewardPicker(None, "sv", [{"item_id": item, "quantity": "1"}], picker.saved.append)
    assert restored.templates.value == "custom"
    tool, values = launch(restored.value)
    assert problems(tool, values)
    restored.rows.controls[0].controls[1].controls[1].on_select(SimpleNamespace(control=ft.Dropdown(value="50")))
    assert not problems(tool, launch(picker.saved[-1])[1])


def test_the_activity_only_swallows_the_unmounted_control_race(monkeypatch):
    async def wake(_):
        pass
    monkeypatch.setattr(asyncio, "sleep", wake)
    activity = PixelActivity()
    def detached():
        raise RuntimeError("PixelActivity must be added to the page first")
    activity.update = detached
    asyncio.run(activity._animate())
    def broken():
        raise RuntimeError("unexpected update failure")
    activity.update = broken
    with pytest.raises(RuntimeError, match="unexpected update failure"):
        asyncio.run(activity._animate())


def swsh_raid(tmp_path, name, boss):
    """The Max Raid (Host) form with `boss` (an encrypted party PK8) as its boss."""
    path = tmp_path / f"{name}.pk8"
    path.write_bytes(boss)
    tool = next(t for game in GAMES for t in game.tools if t.key == "swsh-raid-host")
    return tool, {"--raid-boss": {"file": str(path)}, "--offer-file": {"file": str(path)}}


def hoothoot():
    import json
    from pathlib import Path
    ads = json.loads((Path(__file__).parent / "data" / "swsh_raid_adverts.json").read_text())
    return bytes.fromhex(ads["boss_hoothoot"])


def test_a_den_s_rewards_are_what_the_picker_offers_and_what_the_host_sends(picker, tmp_path):
    """An emulated Shield host's Hoothoot sat in table 30, slot 1. The picker offers that slot's items
    only, every one at its bonus count or the chosen quantity, the host sends them unchanged, and each
    passes the guest's check (0x01032570)."""
    from pokeldn.app.command import reward_den
    from pokeldn.swsh import raid as swsh_raid_records
    import swsh_host
    tool, values = swsh_raid(tmp_path, "hoothoot", hoothoot())
    view = rewards.RewardPicker(None, "swsh", [], picker.saved.append, den=lambda: reward_den(tool, values))
    select(view, "den")
    quantity(view, "7")
    values["--raid-reward"] = picker.saved[-1]
    assert not problems(tool, values)
    args = swsh_host.build_parser().parse_args(build(tool, values, {}, Settings()))
    advert = swsh_host.raid_advert(swsh_host.build_advert(swsh_host.load_advert(str(swsh_raid_records.DEN_ADVERT))),
                                   swsh_raid_records.boss_record(hoothoot()))
    row, rank = swsh_raid_records.den_of(advert)
    assert row[:2] == [30, 1]
    sent = swsh_host.raid_rewards(args, advert, list(swsh_raid_records.DEN_REWARDS))
    den = swsh_raid_records.reward_choices(row, rank)
    assert sent == [(item, 7 if count is None else count) for item, count in den.items()]
    assert swsh_raid_records.fitting_rewards(row, rank, sent)[1] == []
    assert any(count is None for count in den.values()) and any(count not in (None, 7) for count in den.values())


def test_rewards_outside_the_den_are_refused_by_the_form_and_the_host(picker, tmp_path):
    from pokeldn.app.command import reward_den
    from pokeldn.swsh import pokemon as swsh_pokemon, raid as swsh_raid_records
    from pokeldn import gen8
    import swsh_host
    tool, values = swsh_raid(tmp_path, "hoothoot", hoothoot())
    den = dict(reward_den(tool, values))
    bonus = next(item for item, count in den.items() if count is not None)
    advert = swsh_host.raid_advert(swsh_host.build_advert(swsh_host.load_advert(str(swsh_raid_records.DEN_ADVERT))),
                                   swsh_raid_records.boss_record(hoothoot()))
    for rows, error in (([{"item_id": "1", "quantity": "1"}], "Reward 1 is not one this den gives."),
                        ([{"item_id": str(bonus), "quantity": str(den[bonus] + 1)}],
                         f"Reward 1: this den gives it {den[bonus]} at a time.")):
        values["--raid-reward"] = rows
        assert error in problems(tool, values)
        args = swsh_host.build_parser().parse_args(build(tool, values, {}, Settings()))
        assert swsh_host.raid_rewards(args, advert, []).startswith("not rewards of this den")
    # A boss no den holds: the picker offers nothing and the form says why.
    plain = bytearray(gen8.decrypt(hoothoot()))
    plain[gen8.OFF_SPECIES:gen8.OFF_SPECIES + 2] = (151).to_bytes(2, "little")
    mew = tmp_path / "mew.pk8"
    mew.write_bytes(swsh_pokemon.encrypt(bytes(plain)))
    values["--raid-reward"] = [{"item_id": str(bonus), "quantity": str(den[bonus])}]
    view = rewards.RewardPicker(None, "swsh", values["--raid-reward"], picker.saved.append,
                                den=lambda: reward_den(tool, values))
    assert view.problem.value == "" and not view.add.disabled
    values["--raid-boss"] = {"file": str(mew)}
    view.follow()
    assert view.add.disabled and view.problem.visible
    assert "Choose a boss a den holds before choosing rewards." in problems(tool, values)
