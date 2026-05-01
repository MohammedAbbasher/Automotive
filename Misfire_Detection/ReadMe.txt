                                                            Misfire Detection Script (KiBox2 / CoKpit2)

This script identifies misfire events in an internal combustion engine using the IMEPN signal and computes the 'percentage of misfires over a 100-cycle window', updated every 50 cycles.

How it works
  -A misfire is detected when 'IMEPN ≤ 0'.
  -Misfire events are accumulated in 50-cycle blocks.
  -Every 50 cycles, the script evaluates the last 100 cycles (two consecutive blocks) to compute the misfire rate.

Requirements
  -The script is designed for use in **CoKpit2** (KiBox2 software).
  -All variables must be defined and initialized in the Variables table (right-side panel) before running the script.
  -Typical initial values for variables should be set to '0'.
  -Copy and paste the script in the 'User Calculator' window.

Outputs
  -'Out1': Instantaneous misfire flag (0 or 1)
  -'Out2': Misfire percentage over the last 100 cycles (updated every 50 cycles)
