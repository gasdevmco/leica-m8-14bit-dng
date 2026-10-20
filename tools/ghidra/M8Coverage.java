// How much of the M8 PXA image Ghidra decoded as instructions vs data vs undefined, so a
// "no references" result can be weighed (code Ghidra never decoded contributes no references).
// @category M8
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Listing;

public class M8Coverage extends GhidraScript {
    @Override
    protected void run() throws Exception {
        Listing l = currentProgram.getListing();
        AddressSet code = new AddressSet(toAddr(0x20000), toAddr(0xD0000 - 1));   // code region (strings start ~0xD0000)
        long insn = 0, data = 0, undef = 0;
        for (var cu : l.getCodeUnits(code, true)) {
            if (cu instanceof ghidra.program.model.listing.Instruction) insn += cu.getLength();
            else if (((ghidra.program.model.listing.Data) cu).isDefined()) data += cu.getLength();
            else undef += cu.getLength();
        }
        println(String.format("M8COV code-region bytes: instructions %d, defined data %d, undefined %d (%.1f%% instructions)",
                insn, data, undef, 100.0 * insn / (insn + data + undef)));
        println("M8COV functions " + currentProgram.getFunctionManager().getFunctionCount()
                + ", func at 0x2C9F4: " + (getFunctionAt(toAddr(0x2C9F4)) != null));
    }
}
