import sys
import re

def parse_log(filename, marker):
    count = 0
    
    # print(f"{'Result #':<10} | {'Output'}")
    # print("-" * 80)

    try:
        with open(filename, 'r') as f:
            for line in f:
                if marker in line:
                    count += 1
                    # Extract the content after the marker
                    content = line.split(marker, 1)[1].strip()

                    # if count == 1:  #==4 (if all functions in serial)
                    # --- Special Logic for Result 4 ---
                    # We use Regex to find the specific keys instead of parsing the whole dict
                    # to avoid printing the massive arrays.
                    
                    # Pattern to find 'chi2': 123.456
                    chi2_match = re.search(r"'chi2':\s*([\d\.]+)", content)
                    
                    # Pattern to find 'p_value': np.float64(0.123) OR just 0.123
                    # We look for the number inside the np.float64() wrapper
                    p_val_match = re.search(r"'p_value':\s*(?:np\.float64\()([0-9\.\-eE]+)\)", content)
                    
                    chi2 = chi2_match.group(1) if chi2_match else "Not Found"
                    p_val = p_val_match.group(1) if p_val_match else "Not Found"
                    
                    print(f"Result {count:<3} (F) | {{'chi2': {chi2}, 'p_value': {p_val}}}")
                    
                    # else:
                    #     # --- Logic for Results 1, 2, 3, 5 ---
                    #     # Print the full content exactly as it appears in the log
                    #     print(f"Result {count:<3}     | {content}")

    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")

def parse_custom_log(filename, marker):
    count = 0
    with open(filename, 'r') as f:
        for line in f:
            if marker in line:
                count += 1
                print(f"Result {count:<3} | {line}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        parse_log(file_path, "[AnalyticsExecutor] [site-1] Final result:")
        parse_log(file_path, "[AnalyticsExecutor] [site-1] Final reference result:")
        parse_custom_log(file_path, "KAJU")
    else:
        print("No logfile path provided. Usage: python parse_result.py <file_path>")
        sys.exit(1)
    