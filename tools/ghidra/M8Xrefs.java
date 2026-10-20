// Report every reference Ghidra knows into candidate address ranges from outside them,
// plus Ghidra's function body for each range start. Second opinion for tools/m8_reclaim.py.
// Args: name:lo:hi ... (hex). Output lines start with "M8XREF".
// @category M8
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class M8Xrefs extends GhidraScript {
    @Override
    protected void run() throws Exception {
        println("M8XREF functions " + currentProgram.getFunctionManager().getFunctionCount());
        for (String arg : getScriptArgs()) {
            String[] p = arg.split(":");
            long lo = Long.parseLong(p[1], 16), hi = Long.parseLong(p[2], 16);
            Function f = getFunctionAt(toAddr(lo));
            println("M8XREF " + p[0] + " range " + p[1] + "-" + p[2] + " ghidra_func "
                    + (f == null ? "none" : f.getBody().getMinAddress() + "-" + f.getBody().getMaxAddress()));
            int n = 0;
            for (long x = lo; x < hi; x++) {
                for (Reference r : getReferencesTo(toAddr(x))) {
                    long from = r.getFromAddress().getOffset();
                    if (from >= lo && from < hi) continue;
                    Function ff = getFunctionContaining(r.getFromAddress());
                    println("M8XREF   from " + r.getFromAddress() + " to " + toAddr(x) + " " + r.getReferenceType()
                            + " in " + (ff == null ? "?" : ff.getName() + "@" + ff.getEntryPoint()));
                    n++;
                }
            }
            println("M8XREF " + p[0] + " outside_refs " + n);
        }
    }
}
