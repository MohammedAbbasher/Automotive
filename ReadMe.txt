                                                                                                  Torque Ramp Analysis Tool

Overview:

	-This tool analyzes torque ramp-up behavior of an internal combustion engine using experimental Excel data.
	-The tool analyzes multiple torque ramp cycles and automatically selects the fastest transient response (shortest ramp), 
	  based on the time between torque rise initiation and reaching 90% of the target torque for each engine speed.


Features:

	-Automatic processing of multiple Excel files
	-Detection of torque rise start using gradient-based logic
	-Detection of 90% target torque crossing
	-High-resolution Akima interpolation for accurate signal analysis
	-Noise-aware thresholding and robust ramp detection
	-Automatic generation of detailed plots:
		-Main: Torque curve
  		-In comparison: Requested Torque
		-Additional signals (A–I channels)
	-Optional export of processed data to Excel
	-Summary file with ramp durations for all RPMs	

Input Requirements

	1. Target File (Excel)

		Must contain:
			-Column 1 → Engine speed (RPM)
			-Column 2 → Target torque (Nm)

		For reference please see the provided file: Test_Target_90

	2. Measurement Files

		 -Format: '.xlsx'
		 -Each input file must include the engine speed (RPM) as a four-digit number placed immediately before the file extension.
		 -Time Column: Must be labeled Time
		 -Data Start Row: All signal data begins from Row 4
		 -Header Row: Column headers must be in Row 1
		 -Required Columns:

			-Time → in milliseconds
			-Torque → in Nm
			-SPEED → engine speed
	
		-Optional Columns:
			-Requested_Torque
			-Additional signals: 'A, B, C, D, ...'
		
		Note: The code dynamically locates the required signals within the Excel files, meaning that the column order is not important and additional signals can be present without affecting the analysis.
			The placeholder signal names (A to I) can be easily modified in the code to match user-specific naming conventions.

		The results shown in this example are representative of real test scenarios. The tool has been validated using real experimental data and benchmarked against industry-standard software such as Concerto.
	
		For reference please see the provided file: Test_9000.xlsx



How It Works

	The script performs two tightly coupled tasks:

		1.Selects the best ramp event (shortest one)
		2.Analyzes that ramp precisely using signal processing


	1. Ramp Identification (Cycle Selection)

		Instead of analyzing the full dataset, the script:
			-Scans the signal for valid ramp starting points (low torque region)
			-For each candidate start:
				-Searches forward until 90% of target torque is reached
				-Computes the duration of that ramp
				-Compares all candidates and selects the ramp with the shortest time to reach 90% target torque

	2. Ramp Analysis (Signal Processing on Selected Ramp)

		Once the optimal ramp is identified, the script performs a refined, multi-layer analysis:

			2.1 Signal Conditioning:
				-Cleans the data (removes NaNs, sorts, removes duplicates)
				-Normalizes time around the ramp event
				-Applies high-resolution reconstruction using Akima interpolation (with fallback to PCHIP / spline)

			2.2 Coupled Rise Detection (Physics + Numerics)

				The start of torque rise is detected using a hybrid method:

					-Baseline estimation → rolling median
					-Noise estimation → dynamic threshold
					-Gradient analysis → detects rapid physical change

				The rise point is identified when Torque exceeds a dynamic threshold, andThe rate of change (gradient) is consistently high

				Fallback logic ensures robustness if gradient detection fails.

			2.3 Robust 90% Target Detection

				-Instead of a simple threshold crossing, the script uses hysteresis-based detection, which dectates tha torque must remain above 90% of target for multiple samples
				which prevents false positives due to noise or oscillations

				-If 90% is not reached the maximum torque value is used as a fallback


Usage

	-Run the script:
	-You will be prompted to enter:
		1. Target file path it should start with file:/// e.g: 

			file:///C:/TorqueAnalyzer/Test_Target_90.xlsx

		2. Folder containing measurement files, e.g:
			C:/TorqueAnalyzer
		3. Output folder name
		4. To Save results in an excel sheet