package org.pokeldn.usbprobe;

import static org.junit.Assert.*;
import org.junit.Test;

public class SetupTest {
    // Each row of docs/gui.md, Android setup requirements, and the order the checks must run in.
    @Test public void statesFollowTheSetupTable() {
        assertEquals(Setup.State.NO_DEVICE, Setup.decide(false, false, false, false, null));
        assertEquals(Setup.State.UNSUPPORTED_BRIDGE, Setup.decide(false, true, false, false, null));
        assertEquals(Setup.State.NEEDS_PERMISSION, Setup.decide(true, true, false, false, null));
        assertEquals(Setup.State.PERMISSION_DENIED, Setup.decide(true, false, false, true, "stale"));
        assertEquals(Setup.State.CHECKING, Setup.decide(true, false, true, false, null));
        assertEquals(Setup.State.HANDSHAKE_FAILED, Setup.decide(true, false, true, false, "timeout"));
        assertEquals(Setup.State.READY, Setup.decide(true, false, true, true, ""));
    }

    @Test public void nativeUsbAndTheCp210xAreBoards() {
        assertTrue(Setup.isBoard(0x303a, 0x1001));
        assertTrue(Setup.isBoard(0x10c4, 0xea60));
        assertTrue(Setup.isCp210x(0x10c4, 0xea60));
        assertFalse(Setup.isCp210x(0x303a, 0x1001));
        assertFalse(Setup.isBoard(0x303a, 0x0002));
        assertFalse(Setup.isBoard(0x10c4, 0xea61));
        assertFalse(Setup.isBoard(0x1a86, 0x7523));     // a CH340: a bridge the app does not drive
        assertTrue(Setup.isBridge(0x1a86));
        assertFalse(Setup.isBridge(0x303a));
    }

    @Test public void handshakeErrorIsShown() {
        assertTrue(Setup.guidance(Setup.State.HANDSHAKE_FAILED, "Google", "radio protocol 3").contains("radio protocol 3"));
        assertTrue(Setup.guidance(Setup.State.NO_DEVICE, "OnePlus", null).contains("OTG connection"));
    }
}
