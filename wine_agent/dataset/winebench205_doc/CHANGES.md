# winebench205_doc on Vulcan

Rebuilt on Vulcan on 2026-11-24 from `incoming/winebench_2026-11-24/winebench/subset/winebench_subset.json` (205 functions,
Wine 11.19) with `vulcan/build_dataset.sbatch`.

## 2026-11-25: 205 records = 205 - 12 untestable + 12 added (ids 0001-0217 with 12 gaps)

Twelve of the 205 cannot be tested on Vulcan: every test file of theirs crashes on the CLEAN tree there (no outside network
on the compute nodes for winhttp / wininet, no audio device for mf), so the evaluation has nothing to compare with and
reports them as `no_tests`:

    0031 0032 (mf)   0111-0117 (winhttp)   0119 0120 0123 (wininet)

They were moved out of the dataset to `../winebench205_doc_excluded/` (records and doc pages) before any full run started.
Twelve functions were added as 0206-0217 so that 205 testable tasks remain.  They come from WineBench (winebench.json)
minus the 205, with loc.total > 10 and 5 < n_tests_own <= 50, from the categories with the fewest samples; all 39
candidates were built into records and their test files run on the clean tree before choosing
(`incoming/extra_candidates_2026-11-25/candidates_checked.csv`).  The 8 C runtime candidates were left out: their
documentation pages could not be fetched from the documentation repository.

    0206	setupapi!SetupDiEnumDeviceInterfaces	Devices	loc 65	tests 6
    0207	wsdapi!WSDCreateUdpAddress	Devices	loc 30	tests 7
    0208	setupapi!SetupDiGetDeviceInstanceIdA	Devices	loc 20	tests 7
    0209	ntdll!RtlDeleteFunctionTable	Diagnostics	loc 23	tests 7
    0210	pdh!PdhOpenQueryA	Diagnostics	loc 14	tests 12
    0211	ntdll!RtlAddFunctionTable	Diagnostics	loc 14	tests 7
    0212	advapi32!OpenEventLogA	Diagnostics	loc 13	tests 9
    0213	shell32!SHGetDesktopFolder	Windows environment (Shell)	loc 14	tests 14
    0214	kernelbase!VerQueryValueA	User interface	loc 52	tests 6
    0215	kernelbase!GetLocaleInfoA	User interface	loc 42	tests 8
    0216	win32u!GetAncestor	User input and messaging	loc 56	tests 7
    0217	win32u!SendInput	User input and messaging	loc 49	tests 7
