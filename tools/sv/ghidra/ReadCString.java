// Print zero-terminated ASCII strings at exact addresses.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class ReadCString extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String arg : getScriptArgs()) {
            Address cursor = currentProgram.getAddressFactory().getAddress(arg);
            StringBuilder value = new StringBuilder();
            for (int index = 0; index < 256; index++, cursor = cursor.next()) {
                int octet = currentProgram.getMemory().getByte(cursor) & 0xff;
                if (octet == 0) break;
                value.append(octet >= 0x20 && octet <= 0x7e ? (char) octet : '.');
            }
            println(arg + " :: " + value);
        }
    }
}
