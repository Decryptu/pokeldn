"""turbo-lite is turbo without the overlay and the RNG history: every frame test of turbo, run on it."""

import pytest

import tests.test_turbo as turbo
from pokeldn.frlg.rom import buffer_script as bs
from pokeldn.frlg.rom.resident_stubs import STUBS

pytestmark = pytest.mark.skipif(not bs.emulation_available(), reason="needs unicorn")


@pytest.fixture(autouse=True)
def lite(monkeypatch):
    monkeypatch.setattr(turbo, "HOOK", "turbo-lite")


test_an_idle_frame_runs_the_game_then_the_extra_printers = turbo.test_an_idle_frame_runs_the_game_then_the_extra_printers
test_a_lag_frame_runs_only_the_game = turbo.test_a_lag_frame_runs_only_the_game
test_a_printer_the_game_has_not_started_holds_every_extra_call = \
    turbo.test_a_printer_the_game_has_not_started_holds_every_extra_call
test_the_field_pass_runs_both_overworld_callbacks_with_the_new_presses_cleared = \
    turbo.test_the_field_pass_runs_both_overworld_callbacks_with_the_new_presses_cleared
test_with_hold_r_the_passes_run_only_while_r_is_held_and_the_text_extras_always = \
    turbo.test_with_hold_r_the_passes_run_only_while_r_is_held_and_the_text_extras_always
test_a_two_button_hold_needs_both = turbo.test_a_two_button_hold_needs_both
test_hold_r_keeps_the_help_system_off_r = turbo.test_hold_r_keeps_the_help_system_off_r
test_the_budget_starts_a_pass_only_when_it_and_the_game_frame_fit = \
    turbo.test_the_budget_starts_a_pass_only_when_it_and_the_game_frame_fit
test_a_held_back_frame_shrinks_the_kept_cost_until_a_pass_fits_again = \
    turbo.test_a_held_back_frame_shrinks_the_kept_cost_until_a_pass_fits_again
test_no_field_pass_outside_the_overworld = turbo.test_no_field_pass_outside_the_overworld
test_a_pass_whose_cb1_leaves_the_overworld_does_not_run_cb2 = \
    turbo.test_a_pass_whose_cb1_leaves_the_overworld_does_not_run_cb2
test_the_battle_pass_runs_the_battle_callbacks_and_not_the_field_ones = \
    turbo.test_the_battle_pass_runs_the_battle_callbacks_and_not_the_field_ones
test_no_callback_pass_while_a_palette_fade_runs = turbo.test_no_callback_pass_while_a_palette_fade_runs


def test_it_has_no_overlay_or_rng_history_to_set():
    assert not {"p_overlay", "p_ring", "p_watch"} & set(STUBS["turbo-lite"][2])
    with pytest.raises(bs.BufferScriptError, match="not"):
        bs.build_install_resident("turbo-lite", overlay=0x03004220)
