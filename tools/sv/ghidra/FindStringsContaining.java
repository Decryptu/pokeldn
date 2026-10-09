// Print initialized ASCII strings containing any supplied case-insensitive term.
//@category PokeLDN

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.MemoryBlock;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public class FindStringsContaining extends GhidraScript {
    @Override
    public void run() throws Exception {
        List<String> terms = new ArrayList<>();
        for (String arg : getScriptArgs()) terms.add(arg.toLowerCase(Locale.ROOT));
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (!block.isInitialized()) continue;
            Address cursor = block.getStart();
            Address end = block.getEnd();
            StringBuilder text = new StringBuilder();
            Address start = cursor;
            while (cursor.compareTo(end) <= 0) {
                int value = currentProgram.getMemory().getByte(cursor) & 0xff;
                if (value >= 0x20 && value <= 0x7e) {
                    if (text.length() == 0) start = cursor;
                    text.append((char)value);
                }
                else {
                    emit(start, text, terms);
                    text.setLength(0);
                }
                cursor = cursor.next();
                if (cursor == null) break;
            }
            emit(start, text, terms);
        }
    }

    private void emit(Address start, StringBuilder text, List<String> terms) {
        if (text.length() < 4) return;
        String value = text.toString();
        String lower = value.toLowerCase(Locale.ROOT);
        for (String term : terms) {
            if (lower.contains(term)) {
                println(start + " :: " + value);
                return;
            }
        }
    }
}
