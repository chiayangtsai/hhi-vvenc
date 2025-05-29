#!/usr/bin/env python3
"""
auto-encode.py - A script for automated video encoding and BD-rate calculation.

This script automates the process of encoding a raw video file using two
versions of a vvenc-compatible encoder (a reference and a test version).
It runs encodes at 5 specified target bitrates for each encoder.
After encoding, it parses the encoder output to extract PSNR (Y, Cb, Cr)
and actual bitrate achieved for each point.

Finally, it calculates Bjørntegaard Delta Rates (BD-Rates) for Y-PSNR,
Cb-PSNR, and Cr-PSNR to compare the performance of the test encoder
against the reference. The results are saved to a CSV file.

Dependencies:
  - Python 3.6+
  - numpy: For numerical operations, especially for BD-rate calculations.
  - scipy: For interpolation functions used in BD-rate calculations.

Basic Usage:
  python3 scripts/auto-encode.py \\
    --reference_vvenc_executable /path/to/reference/vvencapp \\
    --raw_video_file /path/to/video.yuv \\
    --target_bitrates 250,500,1000,2000,4000 \\
    --reference_tag ref_version_XYZ \\
    --test_tag test_feature_ABC

Note:
  The script currently assumes the input video is YUV and requires manual
  addition of video properties (width, height, framerate, chroma format)
  to the `run_encodes` function's command construction if not using a
  vvenc version that can infer them or if they are not part of the preset.
  These are marked with TODO comments in the `run_encodes` function.
"""

import os
import subprocess
import re
import argparse
import csv
import shutil # For directory cleanup
import numpy as np
from scipy import interpolate # Used by BD-rate functions

# --- BD-Rate Helper Functions ---

def BD_PSNR(R1, PSNR1, R2, PSNR2, piecewise=0):
    """
    Calculates Bjørntegaard Delta PSNR (BD-PSNR) between two rate-distortion curves.
    This function measures the average PSNR difference between two curves,
    integrated over a common range of log-bitrates.

    Parameters:
      R1 (array-like): Bitrates for the reference curve.
      PSNR1 (array-like): PSNR values for the reference curve.
      R2 (array-like): Bitrates for the test curve.
      PSNR2 (array-like): PSNR values for the test curve.
      piecewise (int): If 0, uses polynomial fitting. If 1, uses discrete sum/average.
                       Default is 0.

    Returns:
      float: The BD-PSNR value in dB.
    """
    lR1 = np.log(R1)
    lR2 = np.log(R2)

    # Convert inputs to numpy arrays if they aren't already
    PSNR1 = np.asarray(PSNR1)
    PSNR2 = np.asarray(PSNR2)

    # Fit 3rd degree polynomial to the R-PSNR curve
    try:
        p1 = np.polyfit(lR1, PSNR1, 3)
        p2 = np.polyfit(lR2, PSNR2, 3)
    except (np.linalg.LinAlgError, TypeError, ValueError) as e:
        # Handle cases where fitting might fail (e.g., insufficient points, degenerate data)
        print(f"Error fitting polynomials for BD-PSNR: {e}")
        return np.nan # Return Not-a-Number if fitting fails

    # Determine the integration interval (common range of log-bitrates)
    min_int = max(min(lR1), min(lR2))
    max_int = min(max(lR1), max(lR2))
    
    if max_int <= min_int:
        print("Warning: No overlapping bitrate range for BD-PSNR calculation.")
        return np.nan


    # Integrate PSNR difference
    if piecewise == 0:
        # Integrate the polynomial functions
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        try:
            int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
            int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
        except (TypeError, ValueError) as e: # Handle issues during polyval if p_int is bad
            print(f"Error evaluating polynomial integrals for BD-PSNR: {e}")
            return np.nan
        avg_diff = (int1 - int2) / (max_int - min_int)
    else:
        # Calculate discrete sum/average of PSNR differences
        samples = 100 # Number of samples for discrete integration
        x = np.linspace(min_int, max_int, samples)
        try:
            y1 = np.polyval(p1, x)
            y2 = np.polyval(p2, x)
        except (TypeError, ValueError) as e: # Handle issues during polyval if p1/p2 is bad
            print(f"Error evaluating polynomials for BD-PSNR (piecewise): {e}")
            return np.nan
        avg_diff = np.average(y1 - y2)
    return avg_diff

def BD_RATE(R1, PSNR1, R2, PSNR2, piecewise=0):
    """
    Calculates Bjørntegaard Delta Rate (BD-Rate) between two rate-distortion curves.
    This function measures the average percentage bitrate difference for the same
    quality (PSNR), integrated over a common PSNR range.

    Parameters:
      R1 (array-like): Bitrates for the reference curve.
      PSNR1 (array-like): PSNR values for the reference curve.
      R2 (array-like): Bitrates for the test curve.
      PSNR2 (array-like): PSNR values for the test curve.
      piecewise (int): If 0, uses polynomial fitting. If 1, uses discrete sum/average.
                       Default is 0.

    Returns:
      float: The BD-Rate value as a percentage.
    """
    # Convert inputs to numpy arrays if they aren't already
    R1 = np.asarray(R1)
    R2 = np.asarray(R2)
    lPSNR1 = np.asarray(PSNR1) # Use PSNR directly as the independent variable for fitting
    lPSNR2 = np.asarray(PSNR2)

    # Fit 3rd degree polynomial to the PSNR-log(Rate) curve
    try:
        p1 = np.polyfit(lPSNR1, np.log(R1), 3)
        p2 = np.polyfit(lPSNR2, np.log(R2), 3)
    except (np.linalg.LinAlgError, TypeError, ValueError) as e:
        print(f"Error fitting polynomials for BD-Rate: {e}")
        return np.nan

    # Determine the integration interval (common range of PSNR values)
    min_int = max(min(lPSNR1), min(lPSNR2))
    max_int = min(max(lPSNR1), max(lPSNR2))

    if max_int <= min_int:
        print("Warning: No overlapping PSNR range for BD-Rate calculation.")
        return np.nan

    # Integrate log(Rate) difference
    if piecewise == 0:
        # Integrate the polynomial functions
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)
        try:
            int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
            int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
        except (TypeError, ValueError) as e:
            print(f"Error evaluating polynomial integrals for BD-Rate: {e}")
            return np.nan

        log_avg_diff = (int1 - int2) / (max_int - min_int)
        avg_diff = (np.exp(log_avg_diff) - 1) * 100 # Convert log difference back to percentage
    else:
        # Calculate discrete sum/average of rate differences
        samples = 100 # Number of samples for discrete integration
        x = np.linspace(min_int, max_int, samples)
        try:
            y1 = np.exp(np.polyval(p1, x)) # Rates from log-fitted polynomials
            y2 = np.exp(np.polyval(p2, x))
        except (TypeError, ValueError) as e:
            print(f"Error evaluating polynomials for BD-Rate (piecewise): {e}")
            return np.nan
        
        # Avoid division by zero if y2 contains zeros
        valid_indices = y2 != 0
        if not np.any(valid_indices):
            print("Warning: All y2 values are zero in BD-Rate piecewise calculation.")
            return np.nan
        avg_diff = np.average((y1[valid_indices] - y2[valid_indices]) / y2[valid_indices]) * 100
        
    return avg_diff

# --- Encoder Output Parsing ---

def parse_vvenc_output(log_output):
    """
    Parses vvenc log output to extract PSNR and bitrate.

    Parameters:
      log_output (str): The combined stdout/stderr from a vvenc run.

    Returns:
      dict: A dictionary with 'bitrate', 'psnr_y', 'psnr_cb', 'psnr_cr'.
            Values are float if found, None otherwise.
    """
    metrics = {'bitrate': None, 'psnr_y': None, 'psnr_cb': None, 'psnr_cr': None}
    
    # Regex for PSNR values. Example: "POC LSB YUV    PSNR Y 40.123 dB"
    # This regex is quite specific; might need adjustment if log format varies slightly.
    psnr_y_match = re.search(r"POC.*PSNR Y\s*([0-9]+\.[0-9]+)\s*dB", log_output)
    if psnr_y_match:
        metrics['psnr_y'] = float(psnr_y_match.group(1))
    
    psnr_u_match = re.search(r"POC.*PSNR U\s*([0-9]+\.[0-9]+)\s*dB", log_output) # Cb
    if psnr_u_match:
        metrics['psnr_cb'] = float(psnr_u_match.group(1))
        
    psnr_v_match = re.search(r"POC.*PSNR V\s*([0-9]+\.[0-9]+)\s*dB", log_output) # Cr
    if psnr_v_match:
        metrics['psnr_cr'] = float(psnr_v_match.group(1))
        
    # Regex for actual bitrate. Example: "Bitrate actual   : 1000.12 kbps"
    bitrate_match = re.search(r"Bitrate\s+actual\s*:\s*([0-9]+\.[0-9]+)\s*kbps", log_output)
    if bitrate_match:
        metrics['bitrate'] = float(bitrate_match.group(1))

    # Warning if critical metrics are missing
    if metrics['bitrate'] is None or metrics['psnr_y'] is None:
        missing_fields = [k for k, v in metrics.items() if v is None and k in ['bitrate', 'psnr_y']]
        if missing_fields: # Only warn if bitrate or psnr_y specifically are missing
            print(f"Warning: Could not parse critical metrics from vvenc output. Missing: {missing_fields}. "
                  f"Log sample: '{log_output[:300].replace(chr(10), ' ')}...'") # Show a sample of the log

    return metrics

# --- Encoding Execution ---

def run_encodes(vvenc_exe_path, video_file_path, target_bitrates_kbps, preset, 
                quality_metric_parse_func, temp_output_dir_base, 
                video_width, video_height, video_framerate, video_input_chroma_format="420"):
    """
    Runs vvenc for a list of target bitrates and collects results.

    Parameters:
      vvenc_exe_path (str): Path to the vvenc executable.
      video_file_path (str): Path to the raw YUV input video.
      target_bitrates_kbps (list): List of target bitrate values in kbps.
      preset (str): The preset string (e.g., "medium", "faster").
      quality_metric_parse_func (function): Function to parse encoder log (e.g., parse_vvenc_output).
      temp_output_dir_base (str): Base directory to store temporary output bitstreams.
      video_width (int): Width of the input video.
      video_height (int): Height of the input video.
      video_framerate (int/str): Framerate of the input video.
      video_input_chroma_format (str): Chroma format of input YUV (e.g., "420", "444").

    Returns:
      list: A list of dictionaries, each containing parsed metrics for one encode point.
            Returns fewer than 5 points if some encodes fail or parsing fails critically.
    """
    # Input validation
    if not (os.path.exists(vvenc_exe_path) and os.access(vvenc_exe_path, os.X_OK)):
        raise FileNotFoundError(f"VVenc executable not found or not executable at: {vvenc_exe_path}")
    if not os.path.exists(video_file_path):
        raise FileNotFoundError(f"Video file not found at: {video_file_path}")

    temp_output_dir = os.path.abspath(temp_output_dir_base)
    os.makedirs(temp_output_dir, exist_ok=True) # Create dir if it doesn't exist
    
    results_data = []
    
    print(f"\nRunning encodes with '{os.path.basename(vvenc_exe_path)}' into '{temp_output_dir}'")

    for i, target_br_kbps in enumerate(target_bitrates_kbps):
        # Construct a unique temporary output bitstream filename
        # Using a simple indexed name, ensure it's unique enough for typical use.
        temp_bitstream_filename = f"temp_out_{os.path.basename(vvenc_exe_path)}_{preset}_{i}_{target_br_kbps}kbps.vvc"
        temp_bitstream_path = os.path.join(temp_output_dir, temp_bitstream_filename)
        
        target_br_bps = int(target_br_kbps * 1000) # Convert kbps to bps for vvenc

        # Construct the VVenc command
        command = [
            vvenc_exe_path,
            "-i", video_file_path,
            f"--Size={video_width}x{video_height}", # Video dimensions
            f"--Framerate={video_framerate}",       # Video framerate
            f"--InputChromaFormat={video_input_chroma_format}", # Input chroma format
            "--preset=" + preset,
            "--RateControlMode=VBR", # Using VBR for target bitrate
            "--TargetBitrate=" + str(target_br_bps),
            "-o", temp_bitstream_path,
            "--Verbosity=info" # Ensure logs are rich enough for parsing
        ]
        
        print(f"  Target: {target_br_kbps} kbps. CMD: {' '.join(command)}")
        
        log_output = "" # Initialize for finally block
        try:
            # Execute the command
            # Timeout set to 5 minutes (300 seconds) per encode; adjust as needed
            proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)
            
            log_output = proc.stdout + "\n" + proc.stderr # Combine stdout and stderr for parsing
            
            # Handle VVenc execution errors
            if proc.returncode != 0:
                print(f"  Warning: VVenc exited with error (code {proc.returncode}) for target bitrate {target_br_kbps} kbps.")
                print(f"  VVenc stderr: {proc.stderr.strip()}")
                print(f"  VVenc stdout: {proc.stdout.strip()}")
                results_data.append({
                    'target_bitrate_kbps': target_br_kbps, 
                    'error': 'vvenc_execution_error', 
                    'returncode': proc.returncode,
                    'log_snippet': log_output[:500] # Store a snippet for debugging
                })
                continue # Skip parsing for this point, proceed to next bitrate

            # Parse metrics from log output
            parsed_metrics = quality_metric_parse_func(log_output)
            parsed_metrics['target_bitrate_kbps'] = target_br_kbps # Add target for reference

            # Store results even if some metrics are None (BD-rate calc will handle this)
            results_data.append(parsed_metrics)
            if parsed_metrics.get('bitrate') and parsed_metrics.get('psnr_y'):
                 print(f"    Achieved: {parsed_metrics['bitrate']:.2f} kbps, PSNR Y: {parsed_metrics['psnr_y']:.3f} dB")
            else:
                print(f"    Warning: Could not parse full metrics for {target_br_kbps} kbps. Data: {parsed_metrics}")


        except subprocess.TimeoutExpired:
            print(f"  Error: VVenc command timed out for target bitrate {target_br_kbps} kbps.")
            results_data.append({'target_bitrate_kbps': target_br_kbps, 'error': 'timeout'})
        except Exception as e: # Catch any other unexpected errors during subprocess or parsing
            print(f"  An unexpected error occurred for target bitrate {target_br_kbps} kbps: {e}")
            results_data.append({
                'target_bitrate_kbps': target_br_kbps, 
                'error': str(e), 
                'log_snippet': log_output[:500]
            })
        finally:
            # Clean up the temporary bitstream file
            if os.path.exists(temp_bitstream_path):
                try:
                    os.remove(temp_bitstream_path)
                except OSError as e:
                    print(f"  Warning: Could not remove temporary file {temp_bitstream_path}: {e}")
                    
    return results_data

# --- Test Executable Finder ---

def find_test_vvenc_executable(repo_root='.'):
    """
    Tries to find a vvenc executable compiled from the current project.
    Checks a list of common relative paths from the repository root.

    Parameters:
      repo_root (str): The path to the repository root.

    Returns:
      str: The absolute path to the first executable found.

    Raises:
      FileNotFoundError: If no executable is found in common locations.
    """
    common_paths = [ # Ordered roughly by likelihood or common build patterns
        'bin/release/vvencapp', 'bin/debug/vvencapp', # Common for solution builds
        'bin/vvencapp',
        'build/bin/release/vvencapp', 'build/bin/debug/vvencapp',
        'build/bin/vvencapp',
        'build/release/vvencapp', 'build/debug/vvencapp',
        'build/vvencapp', 
        'vvencapp', # If built in-place at root (less common for projects)
        # Windows variants (assuming .exe extension)
        'bin/release/vvencapp.exe', 'bin/debug/vvencapp.exe',
        'bin/vvencapp.exe',
        'build/bin/release/vvencapp.exe', 'build/bin/debug/vvencapp.exe',
        'build/bin/vvencapp.exe',
        'build/release/vvencapp.exe', 'build/debug/vvencapp.exe',
        'build/vvencapp.exe',
        'vvencapp.exe',
        # Older/alternative names if any (e.g., vvenc)
        'bin/release/vvenc', 'bin/debug/vvenc', 'bin/vvenc',
        'build/bin/release/vvenc', 'build/bin/debug/vvenc', 'build/bin/vvenc',
        'build/release/vvenc', 'build/debug/vvenc', 'build/vvenc', 'vvenc',
        'bin/release/vvenc.exe', 'bin/debug/vvenc.exe', 'bin/vvenc.exe',
        'build/bin/release/vvenc.exe', 'build/bin/debug/vvenc.exe', 'build/bin/vvenc.exe',
        'build/release/vvenc.exe', 'build/debug/vvenc.exe', 'build/vvenc.exe', 'vvenc.exe',
    ]

    for rel_path in common_paths:
        # The repo_root is the parent of the 'scripts' directory.
        candidate_path = os.path.join(repo_root, rel_path)
        if os.path.exists(candidate_path) and os.access(candidate_path, os.X_OK):
            return os.path.abspath(candidate_path) # Return absolute path for clarity
    
    # If no executable is found after checking all paths
    raise FileNotFoundError(
        f"Test vvenc executable not found in common locations relative to '{os.path.abspath(repo_root)}'.\n"
        "Searched paths included variations of: ./bin, ./build/bin, ./build, etc.\n"
        "Please build the test vvenc executable or ensure it's in one of these locations."
    )

# --- Main Function ---

def main():
    """
    Main function to parse arguments, run encodes, calculate BD-rates, and save results.
    """
    parser = argparse.ArgumentParser(
        description="Automated video encoding using vvenc and BD-rate calculation.",
        formatter_class=argparse.RawTextHelpFormatter # To allow for better formatting of help
    )
    
    # --- Argument Parsing ---
    parser.add_argument("--reference_vvenc_executable", type=str, required=True, 
                        help="Path to the reference vvenc executable (e.g., /path/to/vvencappReference).")
    parser.add_argument("--raw_video_file", type=str, required=True, 
                        help="Path to the raw YUV video file (e.g., /path/to/video.yuv).")
    parser.add_argument("--target_bitrates", type=str, required=True, 
                        help="Comma-separated list of 5 target bitrates in kbps (e.g., \"250,500,1000,2000,4000\").")
    parser.add_argument("--reference_tag", type=str, required=True, 
                        help="Tag for the reference encodes, used in output filenames (e.g., 'ref_v1.0').")
    parser.add_argument("--test_tag", type=str, required=True, 
                        help="Tag for the test encodes, used in output filenames (e.g., 'test_feature_X').")
    
    # Arguments for video properties - these are crucial for YUV inputs
    parser.add_argument("--width", type=int, required=True, help="Width of the raw video.")
    parser.add_argument("--height", type=int, required=True, help="Height of the raw video.")
    parser.add_argument("--framerate", type=str, required=True, 
                        help="Framerate of the raw video (can be int or fraction like 30000/1001).")
    parser.add_argument("--input_chroma_format", type=str, default="420", 
                        help="Input chroma format for YUV (e.g., 400, 420, 422, 444). Default: 420.")
    parser.add_argument("--preset", type=str, default="medium",
                        help="Preset to use for both reference and test encodes (e.g., medium, fast, faster). Default: medium.")


    args = parser.parse_args()

    # --- Initial Argument Validation ---
    print("Parsed arguments:")
    print(f"  Reference vvenc executable: {args.reference_vvenc_executable}")
    if not (os.path.exists(args.reference_vvenc_executable) and os.access(args.reference_vvenc_executable, os.X_OK)):
        print(f"Error: Reference vvenc executable '{args.reference_vvenc_executable}' not found or not executable.")
        return 1
        
    print(f"  Raw video file: {args.raw_video_file}")
    if not os.path.exists(args.raw_video_file):
        print(f"Error: Raw video file '{args.raw_video_file}' not found.")
        return 1

    try:
        parsed_bitrates_str = args.target_bitrates.split(',')
        if len(parsed_bitrates_str) != 5:
            # Error if not exactly 5 bitrates
            raise ValueError("Exactly 5 comma-separated target bitrates must be provided.")
        parsed_bitrates = [float(br.strip()) for br in parsed_bitrates_str] # strip whitespace
        if any(br <= 0 for br in parsed_bitrates):
            raise ValueError("All target bitrates must be positive numbers.")
        print(f"  Target bitrates (kbps): {parsed_bitrates}")
    except ValueError as e:
        print(f"Error parsing target bitrates ('{args.target_bitrates}'): {e}")
        return 1

    print(f"  Video Properties: {args.width}x{args.height} @{args.framerate}fps, Chroma: {args.input_chroma_format}")
    print(f"  Preset for encodes: {args.preset}")
    print(f"  Reference tag: {args.reference_tag}")
    print(f"  Test tag: {args.test_tag}")

    # --- Locate Test Executable ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Assume repo root is the parent directory of the 'scripts' folder
    repo_root_guess = os.path.abspath(os.path.join(script_dir, '..')) 
    
    test_vvenc_executable = None
    try:
        print(f"\nAttempting to find test executable in repo root: {repo_root_guess}")
        test_vvenc_executable = find_test_vvenc_executable(repo_root_guess)
        print(f"  Found test vvenc executable: {test_vvenc_executable}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please ensure the test vvenc executable is built and in a searchable path.")
        return 1 # Exit if test executable is not found

    # --- Setup Temporary Directories ---
    # Base directory for all temporary outputs, created where the script is run
    temp_dir_base = os.path.join(os.getcwd(), f"temp_encode_outputs_{args.reference_tag}_{args.test_tag}")
    temp_ref_dir = os.path.join(temp_dir_base, "ref")
    temp_test_dir = os.path.join(temp_dir_base, "test")
    
    # Clean up existing temp directories from a previous run if any
    if os.path.exists(temp_dir_base):
        print(f"Cleaning up existing temporary directory: {temp_dir_base}")
        try:
            shutil.rmtree(temp_dir_base)
        except OSError as e:
            print(f"Warning: Could not remove old temp directory {temp_dir_base}: {e}. Files might be in use.")
            # Depending on policy, could exit here or try to continue by creating uniquely named dirs.

    # run_encodes will create these, but doing it here helps confirm writability early.
    try:
        os.makedirs(temp_ref_dir, exist_ok=True)
        os.makedirs(temp_test_dir, exist_ok=True)
    except OSError as e:
        print(f"Error creating temporary directories: {e}")
        return 1

    reference_data = []
    test_data = []

    try:
        # --- Run Reference Encodings ---
        print("\n--- Starting Reference Encodings ---")
        reference_data = run_encodes(
            args.reference_vvenc_executable, 
            args.raw_video_file, 
            parsed_bitrates, 
            args.preset,
            parse_vvenc_output, 
            temp_ref_dir,
            args.width, args.height, args.framerate, args.input_chroma_format
        )
        print("\nReference Data Collected:")
        for i, item in enumerate(reference_data):
            print(f"  Point {i+1}: {item}")

        # --- Run Test Encodings ---
        if test_vvenc_executable: # Should always be true due to earlier check, but good practice
            print("\n--- Starting Test Encodings ---")
            test_data = run_encodes(
                test_vvenc_executable, 
                args.raw_video_file, 
                parsed_bitrates, 
                args.preset,
                parse_vvenc_output, 
                temp_test_dir,
                args.width, args.height, args.framerate, args.input_chroma_format
            )
            print("\nTest Data Collected:")
            for i, item in enumerate(test_data):
                print(f"  Point {i+1}: {item}")
        else: # Should not be reached if initial check for test_vvenc_executable is strict
            print("\nCritical Error: Test executable not available for test encodings.")
            return 1


        # --- BD-Rate Calculation ---
        bd_metrics_results = {}
        num_expected_points = 5

        # Filter out points with errors or missing critical data before BD-rate calculation
        valid_ref_points = [d for d in reference_data if d and 'error' not in d and d.get('bitrate') is not None and d.get('psnr_y') is not None]
        valid_test_points = [d for d in test_data if d and 'error' not in d and d.get('bitrate') is not None and d.get('psnr_y') is not None]

        if len(valid_ref_points) < num_expected_points or len(valid_test_points) < num_expected_points:
            print(f"\nError: Not enough valid data points to calculate BD-rates. Need {num_expected_points} for each set.")
            print(f"  Valid reference points collected: {len(valid_ref_points)}")
            print(f"  Valid test points collected: {len(valid_test_points)}")
        else:
            print("\n--- Calculating BD-Metrics ---")
            try:
                # Prepare data for BD-Rate functions
                # Ensure data is sorted by bitrate before fitting, though polyfit doesn't strictly require it,
                # it's good practice for interpreting curves. BD-rate functions might also assume sorted data.
                valid_ref_points.sort(key=lambda x: x['bitrate'])
                valid_test_points.sort(key=lambda x: x['bitrate'])

                R1 = np.array([d['bitrate'] for d in valid_ref_points])
                PSNR1_Y = np.array([d['psnr_y'] for d in valid_ref_points])
                
                R2 = np.array([d['bitrate'] for d in valid_test_points])
                PSNR2_Y = np.array([d['psnr_y'] for d in valid_test_points])

                bd_rate_y = BD_RATE(R1, PSNR1_Y, R2, PSNR2_Y, piecewise=0)
                bd_metrics_results['BD_RATE_Y_PSNR'] = bd_rate_y
                # print(f"  BD-Rate Y-PSNR: {bd_rate_y:.4f}%") # Now written to CSV

                # For Cb and Cr, ensure there are enough valid points
                PSNR1_Cb = np.array([d['psnr_cb'] for d in valid_ref_points if d.get('psnr_cb') is not None])
                PSNR2_Cb = np.array([d['psnr_cb'] for d in valid_test_points if d.get('psnr_cb') is not None])
                if len(PSNR1_Cb) == num_expected_points and len(PSNR2_Cb) == num_expected_points:
                    # Assuming R1 and R2 are still applicable if all points had Cb
                    bd_rate_cb = BD_RATE(R1, PSNR1_Cb, R2, PSNR2_Cb, piecewise=0)
                    bd_metrics_results['BD_RATE_Cb_PSNR'] = bd_rate_cb
                else:
                    print(f"  Warning: Insufficient valid Cb PSNR data points for BD-Rate Cb. Ref: {len(PSNR1_Cb)}, Test: {len(PSNR2_Cb)}")
                    bd_metrics_results['BD_RATE_Cb_PSNR'] = np.nan # Store NaN if not calculable

                PSNR1_Cr = np.array([d['psnr_cr'] for d in valid_ref_points if d.get('psnr_cr') is not None])
                PSNR2_Cr = np.array([d['psnr_cr'] for d in valid_test_points if d.get('psnr_cr') is not None])
                if len(PSNR1_Cr) == num_expected_points and len(PSNR2_Cr) == num_expected_points:
                    bd_rate_cr = BD_RATE(R1, PSNR1_Cr, R2, PSNR2_Cr, piecewise=0)
                    bd_metrics_results['BD_RATE_Cr_PSNR'] = bd_rate_cr
                else:
                    print(f"  Warning: Insufficient valid Cr PSNR data points for BD-Rate Cr. Ref: {len(PSNR1_Cr)}, Test: {len(PSNR2_Cr)}")
                    bd_metrics_results['BD_RATE_Cr_PSNR'] = np.nan # Store NaN
            
            except Exception as e: # Catch errors from numpy/scipy during BD-rate calculations
                print(f"Error during BD-rate calculation process: {e}")
                # Ensure all potential keys are set to NaN if calculation fails midway
                bd_metrics_results.setdefault('BD_RATE_Y_PSNR', np.nan)
                bd_metrics_results.setdefault('BD_RATE_Cb_PSNR', np.nan)
                bd_metrics_results.setdefault('BD_RATE_Cr_PSNR', np.nan)
            
            # --- CSV Output Generation ---
            if bd_metrics_results: 
                raw_video_name_part = os.path.splitext(os.path.basename(args.raw_video_file))[0]
                csv_filename = f"results_{raw_video_name_part}_{args.reference_tag}_{args.test_tag}.csv"
                # CSV placed in the current working directory from where the script is run
                csv_filepath = os.path.join(os.getcwd(), csv_filename) 

                print(f"\n--- Writing Results to CSV: {csv_filepath} ---")
                try:
                    with open(csv_filepath, 'w', newline='') as csvfile:
                        fieldnames = ["ChromaComponent", "BD_RATE_percent"]
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        
                        writer.writerow({"ChromaComponent": "Y", 
                                         "BD_RATE_percent": f"{bd_metrics_results.get('BD_RATE_Y_PSNR', np.nan):.4f}"})
                        writer.writerow({"ChromaComponent": "Cb", 
                                         "BD_RATE_percent": f"{bd_metrics_results.get('BD_RATE_Cb_PSNR', np.nan):.4f}"})
                        writer.writerow({"ChromaComponent": "Cr", 
                                         "BD_RATE_percent": f"{bd_metrics_results.get('BD_RATE_Cr_PSNR', np.nan):.4f}"})
                    print(f"BD-Metric results successfully saved to: {csv_filepath}")
                except IOError as e:
                    print(f"Error writing CSV file '{csv_filepath}': {e}")
            else: # Should not happen if the block above is entered, but as a fallback
                print("\nNo BD-Metric results were calculated to save to CSV.")

    finally:
        # --- Cleanup Temporary Directories ---
        if os.path.exists(temp_dir_base):
            print(f"\nCleaning up temporary directory: {temp_dir_base}")
            try:
                shutil.rmtree(temp_dir_base)
                print(f"Temporary directory {temp_dir_base} removed successfully.")
            except OSError as e:
                print(f"Warning: Could not remove temporary directory {temp_dir_base}: {e}")

    print("\nScript finished.")
    print("Remember to verify YUV format parameters (size, framerate, chroma) in your commands if issues arise.")


if __name__ == "__main__":
    # Wrapped main call in a try-catch for any unhandled exceptions at the very top level
    try:
        return_code = main()
        if return_code is not None and return_code != 0:
            print(f"Script exited with error code: {return_code}")
        # exit(return_code if return_code is not None else 0) # This would exit the agent too early
    except Exception as e:
        print(f"An unexpected top-level error occurred: {e}")
        # exit(1) # This would exit the agent too early
