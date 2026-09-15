import json
import sys
import os

def deep_average(data_list):
    """
    Recursively averages numerical values in a list of dictionaries/values.
    Preserves strings and structure from the first item.
    """
    if not data_list:
        return None

    # Determine the type of data we are processing based on the first item
    ref_item = data_list[0]

    # CASE 1: Numeric values -> Calculate Average
    if isinstance(ref_item, (int, float)):
        return sum(data_list) / len(data_list)

    # CASE 2: Dictionaries -> Recurse
    if isinstance(ref_item, dict):
        result = {}
        # Iterate over all keys present in the first dictionary
        for key in ref_item.keys():
            # Collect the values for this key from all dictionaries in the list
            # We filter to ensure the key exists in the other runs
            sub_values = [d[key] for d in data_list if key in d]
            
            if sub_values:
                result[key] = deep_average(sub_values)
        return result

    # CASE 3: Strings/Lists/Other -> Return the first one (do not average)
    return ref_item

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 aggregate_results.py <path_to_file1> <path_to_file2> ...")
        sys.exit(1)

    file_paths = sys.argv[1:]
    loaded_data = []

    # print(f"Aggregating results from {len(file_paths)} files...")

    # Load all JSON files
    for p in file_paths:
        if not os.path.exists(p):
            print(f"Warning: File not found: {p}")
            continue
        try:
            with open(p, 'r') as f:
                loaded_data.append(json.load(f))
        except Exception as e:
            print(f"Error reading {p}: {e}")

    if not loaded_data:
        print("No valid data found to aggregate.")
        sys.exit(1)

    # Calculate averages
    averaged_data = deep_average(loaded_data)

    # Define output filename
    output_file = "averaged_profile_summary.json"
    
    # Save result
    with open(output_file, 'w') as f:
        json.dump(averaged_data, f, indent=2)

    # print(f"----------------------------------------")
    # print(f"Successfully generated: {output_file}")
    # print(f"----------------------------------------")

if __name__ == "__main__":
    main()