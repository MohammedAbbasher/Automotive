import os
import pandas as pd
import logging
import matplotlib.pyplot as plt
import numpy as np
from scipy import interpolate
import math

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ramp_analysis_excel.log"),
        logging.StreamHandler()
    ]
)

def load_data(filepath):
    try:
        return pd.read_excel(filepath, engine='openpyxl')
    except Exception as e:
        logging.exception("Error loading the file %s: %s", filepath, str(e))
        return None

def validate_columns(df, required_columns):
    return all(col in df.columns for col in required_columns)

def extract_rpm_from_filename(filename):
    import re
    match = re.search(r'_(\d{4})(?=\.xlsx)', filename)
    return int(match.group(1)) if match else None

def get_target_torque_by_rpm(rpm, df_target):
    try:
        df_target.columns = df_target.columns.astype(str)  # FIXED: astype instead of ast
        match = df_target[df_target[df_target.columns[0]] == rpm]
        if not match.empty:
            return float(match[df_target.columns[1]].values[0])
    except Exception as e:
        logging.error("Error calculating the target for RPM %s: %s", rpm, str(e))
    return None

def find_shortest_ramp(df, target_torque):
    df_filtered = df.iloc[3:].copy()
    df_filtered['Time'] = pd.to_numeric(df_filtered['Time'], errors='coerce')
    df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
    start_candidates = df_filtered[df_filtered['Torque'] <= 40].index
    shortest_duration = float('inf')
    start_time = end_time = None
    for start in start_candidates:
        for end in range(start + 1, len(df)):
            try:
                tq_value = float(df.loc[end, 'Torque'])
                if tq_value >= 0.9*target_torque:
                    duration = df.loc[end, 'Time'] - df.loc[start, 'Time']
                    if pd.notna(duration) and 0 < duration < shortest_duration:
                        shortest_duration = duration
                        start_time, end_time = df.loc[start, 'Time'], df.loc[end, 'Time']
                    break
            except Exception:
                continue
    if start_time is not None and end_time is not None:
        return df[(df['Time'] >= start_time - 1000) & (df['Time'] <= end_time + 500)], start_time, end_time
    return None, None, None

def interpolate_torque_data(t, torque, factor=10):
    """
    Advanced Akima interpolation for torque data - preserves shape and handles sharp changes
    better than cubic splines for torque curves.
    """
    # Remove NaN values
    valid_mask = ~(np.isnan(t) | np.isnan(torque))
    t_clean = t[valid_mask]
    torque_clean = torque[valid_mask]
    
    if len(t_clean) < 2:
        return t, torque
    
    # Sort the data by time
    sort_idx = np.argsort(t_clean)
    t_sorted = t_clean[sort_idx]
    torque_sorted = torque_clean[sort_idx]
    
    # Remove duplicates to avoid interpolation issues
    t_unique, unique_indices = np.unique(t_sorted, return_index=True)
    torque_unique = torque_sorted[unique_indices]
    
    if len(t_unique) < 2:
        return t, torque
    
    # Create high-resolution time array
    t_high_res = np.linspace(t_unique.min(), t_unique.max(), len(t_unique) * factor)
    
    try:
        # Use Akima interpolation - excellent for preserving data shape
        akima = interpolate.Akima1DInterpolator(t_unique, torque_unique)
        torque_high_res = akima(t_high_res)
        
        # Handle edge cases where Akima might fail
        if np.any(np.isnan(torque_high_res)):
            # Fallback to PCHIP (Piecewise Cubic Hermite Interpolating Polynomial)
            pchip = interpolate.PchipInterpolator(t_unique, torque_unique)
            torque_high_res = pchip(t_high_res)
            
    except Exception as e:
        print(f"Akima interpolation failed: {e}, using cubic spline fallback")
        # Fallback to cubic spline
        cubic_spline = interpolate.CubicSpline(t_unique, torque_unique)
        torque_high_res = cubic_spline(t_high_res)
    
    return t_high_res, torque_high_res


def find_torque_threshold_times(t, torque, target_torque):
    """
    Find torque rise start and 90% target crossing times and values.
    Uses advanced interpolation for precise threshold detection.
    """
    # Use advanced interpolation for threshold detection
    t_interp, torque_interp = interpolate_torque_data(t, torque, factor=20)  # Higher factor for precision
    
    # Convert to pandas Series
    t_series = pd.Series(t_interp)
    torque_series = pd.Series(torque_interp)
    
    print(f"\n=== TORQUE ANALYSIS DEBUG (AKIMA INTERPOLATED) ===")
    print(f"Interpolated data points: {len(t_series)}")
    print(f"Target torque: {target_torque:.1f} Nm")
    print(f"90% threshold: {0.9 * target_torque:.1f} Nm")
    
    # Safety check for empty data
    if len(t_series) == 0 or len(torque_series) == 0:
        print("ERROR: Empty data series")
        return 0, 0, 0, 0
    
    # Use more sophisticated rise detection
    # Calculate rolling median for baseline
    window_size = min(20, len(torque_series) // 10)
    if window_size > 1:
        rolling_median = torque_series.rolling(window=window_size, center=False).median()
        base_torque = rolling_median.iloc[:window_size].median()
    else:
        base_torque = torque_series.iloc[:5].median() if len(torque_series) >= 5 else torque_series.iloc[0]
    
    # Dynamic rise threshold based on noise level
    noise_level = torque_series.iloc[:20].std() if len(torque_series) >= 20 else 1.0
    rise_threshold = base_torque + max(2.0, 3 * noise_level)
    
    # Find rise start using derivative-based approach
    rise_idx = None
    
    # Calculate gradient to find where torque starts increasing significantly
    if len(torque_series) > 10:
        gradient = np.gradient(torque_series.values, t_series.values)
        # Smooth the gradient a bit
        smoothed_gradient = pd.Series(gradient).rolling(window=5, center=True).mean().values
        
        # Find where gradient exceeds threshold
        gradient_threshold = max(5.0, 2 * np.std(smoothed_gradient[:20])) if len(smoothed_gradient) > 20 else 5.0
        
        for i in range(10, len(smoothed_gradient)):
            if (smoothed_gradient[i] > gradient_threshold and 
                torque_series.iloc[i] > rise_threshold and
                all(smoothed_gradient[i:i+3] > gradient_threshold/2)):
                rise_idx = i
                break
    
    # Fallback to simple threshold if gradient method fails
    if rise_idx is None:
        for i in range(len(torque_series)):
            if torque_series.iloc[i] > rise_threshold:
                rise_idx = i
                break
    
    if rise_idx is not None and rise_idx < len(torque_series):
        torque_start_value = torque_series.iloc[rise_idx]
        torque_start_time = t_series.iloc[rise_idx]
    else:
        torque_start_value = torque_series.iloc[0]
        torque_start_time = t_series.iloc[0]
        rise_idx = 0
    
    # Find 90% target crossing with hysteresis to avoid noise
    threshold_90 = 0.90 * target_torque
    target_idx = None
    hysteresis_window = 5  # Require sustained crossing
    
    for i in range(rise_idx, len(torque_series) - hysteresis_window):
        # Check if torque stays above threshold for hysteresis window
        if all(torque_series.iloc[i:i+hysteresis_window] >= threshold_90):
            target_idx = i
            break
    
    if target_idx is None:
        # Find maximum torque if 90% not reached
        max_idx = torque_series.idxmax()
        torque_90_value = torque_series.iloc[max_idx]
        torque_90_time = t_series.iloc[max_idx]
    else:
        torque_90_value = torque_series.iloc[target_idx]
        torque_90_time = t_series.iloc[target_idx]
    
    print(f"Base torque: {base_torque:.1f} Nm")
    print(f"Rise threshold: {rise_threshold:.1f} Nm")
    print(f"Noise level: {noise_level:.2f} Nm")
    print(f"Rise detected at index: {rise_idx}")
    print(f"Torque start: {torque_start_value:.1f} Nm at {torque_start_time:.3f}s")
    print(f"Torque 90%: {torque_90_value:.1f} Nm at {torque_90_time:.3f}s")
    print(f"Time difference: {(torque_90_time - torque_start_time)*1000:.1f}ms")
    print("============================\n")
    
    return torque_start_time, torque_90_time, torque_start_value, torque_90_value


def generate_and_insert_graph(df, output_path, target_torque, start_time, 
                             torque_start_time, torque_90_time, 
                             torque_start_value, torque_90_value,
                             save_excel=True):
    """
    Torque (torque) as main large plot, Requested Torque as smaller subplot below.
    Uses interpolated data for both plotting and threshold markers.
    """
    baseline = start_time - 1000
    df['t_norm'] = pd.to_numeric(df['Time'] / 1000, errors='coerce') - baseline / 1000
    t = pd.to_numeric(df['t_norm'], errors='coerce')

    fig = plt.figure(figsize=(18, 12))
    
    # Create grid with different height ratios - Torque gets more space
    grid = fig.add_gridspec(8, 2, width_ratios=[2, 1], 
                           height_ratios=[1, 1, 1, 1, 1, 1, 1, 1])
    
    # === MAIN PLOT: Torque (large) ===
    ax_Torque = fig.add_subplot(grid[0:4, 0])
    
    y_Torque = None
    y_requested = None
    requested_start_value = None
    requested_90_value = None

    # Plot Torque with interpolation
    if 'Torque' in df.columns:
        y_Torque = pd.to_numeric(df['Torque'], errors='coerce')
    
        # Interpolate for smoother curve
        t_clean = t[~t.isna() & ~y_Torque.isna()]
        y_Torque_clean = y_Torque[~t.isna() & ~y_Torque.isna()]
        
        if len(t_clean) > 1:
            t_interp, y_Torque_interp = interpolate_torque_data(t_clean.values, y_Torque_clean.values, factor=5)
            ax_Torque.plot(t_interp, y_Torque_interp, label='Torque [Nm]', color='black', linewidth=2)
        else:
            ax_Torque.plot(t, y_Torque, label='Torque [Nm]', color='black', linewidth=2)
        
        ax_Torque.set_ylabel("Torque [Nm]", color='black', fontsize=12, fontweight='normal')
        ax_Torque.tick_params(axis='y', labelcolor='black')
        
      

        # Round target_torque UP to the nearest 50
        y_min = y_Torque.min()
        y_max = y_Torque.max()

        margin = 0.1 * (y_max - y_min)  # 10% margin
        ax_Torque.set_ylim(y_min - margin, y_max + margin)
        
        # Add 90% target line
        ax_Torque.axhline(y=target_torque * 0.9, color='limegreen', linestyle='--', 
                         linewidth=2, label=f'Target 90% ({target_torque*0.9:.1f} Nm)')

        # Add vertical lines and markers for Torque (using interpolated threshold values)
        if torque_start_time is not None:
            ax_Torque.axvline(x=torque_start_time, color='red', linestyle='--', 
                             linewidth=2, alpha=0.7, label='Rise Start')
            ax_Torque.scatter(torque_start_time, torque_start_value, color='red', 
                            s=100, zorder=5, edgecolors='white', linewidth=1.5)
        
        if torque_90_time is not None:
            ax_Torque.axvline(x=torque_90_time, color='blue', linestyle='--', 
                             linewidth=2, alpha=0.7, label='90% Target')
            ax_Torque.scatter(torque_90_time, torque_90_value, color='blue', 
                            s=100, zorder=5, edgecolors='white', linewidth=1.5)

        ax_Torque.grid(True, alpha=0.3)
        ax_Torque.legend(loc='upper left')
        ax_Torque.set_title('TORQUE', fontsize=14, fontweight='normal', pad=10)



    # === SMALL SUBPLOT: REQUESTED TORQUE (below Torque) ===
    ax_requested = fig.add_subplot(grid[5:7, 0])  # Next 2 rows for Requested Torque
    
    # Check for requested torque column (using the column name from your code)
    if 'Requested_Torque' in df.columns:
        y_requested = pd.to_numeric(df['Requested_Torque'], errors='coerce')
        ax_requested.plot(t, y_requested, label='REQUESTED TORQUE [Nm]', color='black', linewidth=1.5)
        ax_requested.set_ylabel("Requested Torque [Nm]", color='bLACK', fontsize=10, fontweight='normal')
        ax_requested.tick_params(axis='y', labelcolor='bLack')
        
        # Set appropriate scale for Requested Torque
        #ax_requested.set_ylim(0, 350)
        
        # Add vertical lines to match Torque plot
        if torque_start_time is not None:
            ax_requested.axvline(x=torque_start_time, color='red', linestyle='--', 
                                linewidth=1.5, alpha=0.7)
            # Get and mark Requested Torque value at rise time
            idx_start = (t - torque_start_time).abs().idxmin()
            if idx_start < len(y_requested):
                requested_start_value = y_requested.iloc[idx_start]
                ax_requested.scatter(torque_start_time, requested_start_value, color='red', 
                                   s=60, zorder=5, edgecolors='white', linewidth=1)
        
        if torque_90_time is not None:
            ax_requested.axvline(x=torque_90_time, color='blue', linestyle='--', 
                                linewidth=1.5, alpha=0.7)
            # Get and mark Requested Torque value at 90% time
            idx_90 = (t - torque_90_time).abs().idxmin()
            if idx_90 < len(y_requested):
                requested_90_value = y_requested.iloc[idx_90]
                ax_requested.scatter(torque_90_time, requested_90_value, color='blue', 
                                   s=60, zorder=5, edgecolors='white', linewidth=1)

        ax_requested.grid(True, alpha=0.3)
        ax_requested.legend(loc='upper left')
        ax_requested.set_xlabel("Time [s]", fontsize=10, fontweight='normal')
        ax_requested.set_title('REQUESTED TORQUE', fontsize=12, fontweight='normal', pad=8)

    # Share x-axis between the two plots
    ax_requested.sharex(ax_Torque)
    
    # Hide x-axis labels on Torque plot since Requested Torque plot will show them
    ax_Torque.tick_params(labelbottom=False)

    # === Annotations (on Torque plot) ===
    if (torque_start_time is not None and torque_90_time is not None and 
        y_Torque is not None and y_requested is not None and
        requested_start_value is not None and requested_90_value is not None):
        
        time_diff = torque_90_time - torque_start_time
        torque_diff = torque_90_value - torque_start_value
        requested_diff = requested_90_value - requested_start_value

        annotation_text = (
          "Time(s)     Torque(Nm)     C_T90%(Nm)     Torque_Req(Nm)\n"
          "---------------------------------------------------------------\n"
          f"{torque_start_time:>9.3f}     {torque_start_value:>11.1f}     {target_torque*0.9:>11.1f}     {requested_start_value:>13.1f}\n"
          f"{torque_90_time:>9.3f}     {torque_90_value:>11.1f}     {target_torque*0.9:>11.1f}     {requested_90_value:>13.1f}\n"
          f"{time_diff:>9.3f}     {torque_diff:>11.1f}     {0:>11.1f}     {requested_diff:>13.1f}"
          )

    ax_Torque.text(0.98, 0.02, annotation_text, transform=ax_Torque.transAxes, fontsize=8,
               verticalalignment='bottom', horizontalalignment='right',
               fontfamily='monospace',
               bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # === RIGHT column subplots ===
    # Create right column axes first
    axs_right = []
    for i in range(7):
        axs_right.append(fig.add_subplot(grid[i, 1]))
        # You need to delete the title from the loop down there
    
    right_plots = [
        (['A', None], 'a', '_a_', 'black', (10, 35), None, None),
        ('B', 'b', '_b_', 'black', (0, 100), '', None),
        ('C', 'c', '_c_', 'black', (0, 100), None, None),
        ('D', 'd', '_d_', 'black', None, 'E', 'e'),
        ('F', 'f', '_f_', 'black', None, 'G', 'g'),
        ('H', 'h', '_h_', 'black', None, None, None),
        ('I', 'i', '_i_', 'black', None, None, None),
        ]

    for ax, plot_info in zip(axs_right, right_plots):
        if len(plot_info) == 7:
            col_name, title, y_label, color, ylim, second_signal, second_label = plot_info
        else:
            col_name, title, y_label, color, ylim = plot_info
            second_signal, second_label = None, None

        if isinstance(col_name, list):
            # Handle multiple signals for the same plot
            for i, signal_col in enumerate(col_name):
                if signal_col in df.columns and signal_col is not None:
                    y_vals = pd.to_numeric(df[signal_col], errors='coerce')
                    line_style = '-' if i == 0 else '--'
                    line_color = color if i == 0 else 'red'  # Different color for second signal
                    line_label = title if i == 0 else second_label
                    ax.plot(t, y_vals, label=line_label, color=line_color, linewidth=1, linestyle=line_style)
        else:
            if col_name in df.columns:
                y_vals = pd.to_numeric(df[col_name], errors='coerce')
                ax.plot(t, y_vals, label=title, color=color, linewidth=1)

        # Add second signal if specified
        if second_signal and second_signal in df.columns and second_label:
            y_vals_second = pd.to_numeric(df[second_signal], errors='coerce')
            ax.plot(t, y_vals_second, label=second_label, color='red', linewidth=1, linestyle='--')

        # Formatting moved inside loop
       # ax.set_title(title, fontsize=9)
        ax.set_ylabel(y_label, fontsize=8)
        if ylim is not None:
            ax.set_ylim(ylim)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)
        ax.tick_params(labelsize=8)

    # After plotting all right-hand figures
        for ax in axs_right:
            ax.set_xlabel("Time [s]")

    # === Save figure ===
    image_path = output_path.replace('.xlsx', '_graph.png')
    title = os.path.splitext(os.path.basename(image_path))[0]
    plt.suptitle(title, fontsize=14, fontweight="bold", y=0.995)
    plt.savefig(image_path, dpi=300, bbox_inches="tight")
    plt.close()

      
def process_file(filepath, output_dir, df_target, save_excel=True):
    df = load_data(filepath)
    if df is None:
        logging.error(f"Failed to load file: {filepath}")
        return None
        
    # Validate required columns
    required_columns = ['SPEED', 'Torque', 'Time']
    if not validate_columns(df, required_columns):
        missing = [col for col in required_columns if col not in df.columns]
        logging.error(f"Missing columns in {filepath}: {missing}")
        return None
    
    rpm = extract_rpm_from_filename(os.path.basename(filepath))
    if rpm is None:
        logging.warning(f"Could not extract RPM from filename: {filepath}")
        return None
        
    target_torque = get_target_torque_by_rpm(rpm, df_target)
    if target_torque is None:
        logging.warning(f"No target torque found for RPM {rpm} in file {filepath}")
        return None

    # DEBUG: Check data quality
    torque_data = pd.to_numeric(df['Torque'], errors='coerce')
    time_data = pd.to_numeric(df['Time'], errors='coerce')
    
    print(f"\n=== PROCESSING RPM {rpm} ===")
    print(f"File: {os.path.basename(filepath)}")
    print(f"Target torque: {target_torque} Nm")
    print(f"Torque range: {torque_data.min():.1f} to {torque_data.max():.1f} Nm")
    print(f"Time range: {time_data.min()} to {time_data.max()} ms")
    print(f"Data points: {len(df)}")
    print(f"NaN values in torque: {torque_data.isna().sum()}")
    print(f"NaN values in time: {time_data.isna().sum()}")

    ramp_df, start_time, end_time = find_shortest_ramp(df, target_torque)
    if ramp_df is None:
        logging.warning(f"No valid ramp found in {filepath} for RPM {rpm}")
        print(f"No ramp found for RPM {rpm}")
        return None
        
    print(f"Found ramp: start={start_time}ms, end={end_time}ms, duration={end_time-start_time}ms")

    # For plotting → keep truncated
    combined_df = pd.concat([df.iloc[:2], ramp_df], ignore_index=True)

    # For Excel → extend until torque returns to baseline
    baseline_torque = torque_data.iloc[:max(5, len(torque_data)//100)].mean()
    tol = 5  # tolerance in Nm
    mask_after_target = (time_data > end_time) & (torque_data.between(baseline_torque - tol, baseline_torque + tol))
    if mask_after_target.any():
        end_index = mask_after_target.idxmax()
    else:
        end_index = len(df) - 1
    df_excel = df.iloc[:end_index+1].copy()

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"ramp_{rpm}.xlsx")

    if save_excel:
        df_excel.to_excel(output_path, index=False, engine='openpyxl')

    # Generate t_norm for plotting (use truncated data)
    baseline = start_time - 1000
    combined_df['t_norm'] = (combined_df['Time'] - baseline) / 1000.0

    # Detect torque thresholds
    torque_signal = pd.to_numeric(combined_df['Torque'], errors='coerce')
    t_norm = combined_df['t_norm']
    
    try:
        if 'interpolate_torque_data' not in globals():
            print("interpolate_torque_data not available, using original data")
            t_start, t_90, torque_start_value, torque_90_value = find_torque_threshold_times(
                t_norm.values, torque_signal.values, target_torque
            )
        else:
            t_clean = t_norm[~t_norm.isna() & ~torque_signal.isna()]
            torque_clean = torque_signal[~t_norm.isna() & ~torque_signal.isna()]
            
            if len(t_clean) > 1:
                t_interp, torque_interp = interpolate_torque_data(t_clean.values, torque_clean.values, factor=10)
                t_start, t_90, torque_start_value, torque_90_value = find_torque_threshold_times(
                    t_interp, torque_interp, target_torque
                )
            else:
                t_start, t_90, torque_start_value, torque_90_value = find_torque_threshold_times(
                    t_norm.values, torque_signal.values, target_torque
                )
        
        logging.info(f"[RPM {rpm}] Torque rise starts at {t_start:.2f} s and hits 90% at {t_90:.2f} s")
        print(f"Thresholds found: rise at {t_start:.2f}s, 90% at {t_90:.2f}s")
        
    except NameError as e:
        if "interpolate_torque_data" in str(e):
            print("interpolate_torque_data not available, using original data")
            t_start, t_90, torque_start_value, torque_90_value = find_torque_threshold_times(
                t_norm.values, torque_signal.values, target_torque
            )
        else:
            logging.error(f"Error finding thresholds for RPM {rpm}: {str(e)}")
            print(f"Threshold error: {str(e)}")
            return None
    except Exception as e:
        logging.error(f"Error finding thresholds for RPM {rpm}: {str(e)}")
        print(f"Threshold error: {str(e)}")
        return None

    generate_and_insert_graph(
        combined_df, output_path, target_torque, start_time,
        t_start, t_90, torque_start_value, torque_90_value,
        save_excel=save_excel
    )

    duration_ms = end_time - start_time
    print(f"Successfully processed RPM {rpm}")
    return rpm, duration_ms / 1000.0

def main():
    target_file_path = input("Please Enter the path to the Excel file with the target values: ").strip()
    df_target = load_data(target_file_path)
    if df_target is None:
        return
    
    # DEBUG: Show available target RPMs
    print("\n=== TARGET FILE DEBUG ===")
    print(f"Target file columns: {df_target.columns.tolist()}")
    print(f"Available RPMs in target file: {df_target[df_target.columns[0]].unique()}")
    print("=========================\n")
    
    input_dir = input("Please Enter the directory path containing the .xlsx files to analyze: ").strip()
    output_subfolder = input("Please Enter the name of the subfolder to be created for the results: ").strip()
    choice = input("Do you want to save the results in Excel? (y/n): ").strip().lower()
    save_excel = choice == 'y'

    output_dir = os.path.join(input_dir, output_subfolder)
    if save_excel:
        os.makedirs(output_dir, exist_ok=True)

    # DEBUG: Check all files and their RPM extraction
    print("\n=== FILE SCAN DEBUG ===")
    all_files = []
    for filename in os.listdir(input_dir):
        if filename.endswith(".xlsx") and filename != os.path.basename(target_file_path):
            rpm = extract_rpm_from_filename(filename)
            print(f"File: {filename} -> Extracted RPM: {rpm}")
            all_files.append((filename, rpm))
    print("========================\n")

    summary_data = []
    for filename, rpm in all_files:
        if rpm is None:
            logging.warning(f"Skipping file {filename} - could not extract RPM")
            continue
            
        # Check if RPM exists in target file
        target_exists = rpm in df_target[df_target.columns[0]].values
        if not target_exists:
            logging.warning(f"Skipping file {filename} - RPM {rpm} not found in target file")
            continue
            
        result = process_file(os.path.join(input_dir, filename), output_dir, df_target, save_excel=save_excel)
        if result:
            summary_data.append(result)

    if save_excel and summary_data:
        summary_df = pd.DataFrame(summary_data, columns=["Engine Speed (RPM)", "Ramp Duration (sec)"])
        summary_df.to_excel(os.path.join(output_dir, "Shortest_Ramp_Summary.xlsx"), index=False, engine='openpyxl')

    logging.info("Analisi completata.")

if __name__ == "__main__":
    main()
