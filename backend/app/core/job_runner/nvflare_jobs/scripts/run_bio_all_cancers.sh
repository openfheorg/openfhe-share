#!/bin/bash

# --- Configuration ---
RUN_EXPERIMENT=true   # Set to 'false' if you already have outputs and just want to aggregate

TARGET_SUCCESSFUL_RUNS=1
MAX_ATTEMPTS=$((TARGET_SUCCESSFUL_RUNS * 2)) # Safety limit
CANCER_TYPES=(
    "Bladder Cancer"
    "Breast Carcinoma"
    "Cancer of Unknown Primary"
    "Colorectal Cancer"
    "Endometrial Cancer"
    "Esophagogastric Carcinoma"
    "Gastrointestinal Neuroendocrine Tumor"
    "Gastrointestinal Stromal Tumor"
    "Glioma"
    "Melanoma"
    "Non-Hodgkin Lymphoma"
    "Non-Small Cell Lung Cancer"
    "Ovarian Cancer"
    "Pancreatic Cancer"
    "Prostate Cancer"
    "Renal Cell Carcinoma"
    "Skin Cancer, Non-Melanoma"
    "Soft Tissue Sarcoma"
    "Thyroid Cancer"

    # # Don't have logistic_reg model for these cancers.
    # "Biliary Cancer"
    # "Head and Neck Carcinoma"
    # "Leukemia"
    # "Meningothelial Tumor"
    # "Mesothelioma"
    # "Other"
    # "Small Cell Lung Cancer"
)
# CANCER_TYPES=(
#     "Non-Small Cell Lung Cancer"
# )

# Biomarker model keys: set "model_keys" in workload_args in config_fed_server.json (e.g. both cox_lasso and logistic_reg in one run).

CONFIG_FILE="jobs/nvflare_job_template/app_server/config/config_fed_server.json"

python3 wheels/APIWheelBuilderCI.py --root . --out-dir wheels >/dev/null
LOCAL_WHEEL="$(find wheels -maxdepth 1 -type f -name 'duality_nvflare_lib-*.whl' | sort | tail -n 1)"
if [ -z "$LOCAL_WHEEL" ]; then
    echo "ERROR: local duality_nvflare_lib wheel was not produced." >&2
    exit 20
fi
python3 -m pip install --force-reinstall --no-index --no-deps "$LOCAL_WHEEL" >/dev/null
export DUALITY_NVFLARE_LIB_UPDATE_DISABLED=1
# for i in {1..5}; do pkill -f stat_analytics; sleep 1; done


for CANCER in "${CANCER_TYPES[@]}"; do
    CANCER_SLUG=$(echo "$CANCER" | tr ' ' '_' | tr '/' '_')
    RUN_PREFIX="outputs/${CANCER_SLUG}"

    sed -i "s/\"cancer_type\": \".*\"/\"cancer_type\": \"$CANCER\"/g" "$CONFIG_FILE"
    echo -e "\t\t\t-------------------- cancer=${CANCER} (model_keys from ${CONFIG_FILE}) --------------------"
    RESULT_FILES=() # Array to store paths of successful output files

    SUCCESS_COUNT=0
    ATTEMPT=1
    if [ "$RUN_EXPERIMENT" = true ]; then
        # echo "Starting Job: Aiming for $TARGET_SUCCESSFUL_RUNS successes..."
        # echo "----------------------------------------"

        # 1. RUNNING THE JOBS
        while [ $SUCCESS_COUNT -lt $TARGET_SUCCESSFUL_RUNS ] && [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
            
            # Define current output index (1, 2, 3, 4, 5)
            CURRENT_RESULT_NUM=$((SUCCESS_COUNT + 1))
            
            # Define the output directory and expected result file path (unique per cancer)
            OUT_DIR="${RUN_PREFIX}/stat_analytics_${CURRENT_RESULT_NUM}"
            RESULT_FILE="${OUT_DIR}/server/job-results/simulate_job/profile_summary.json"
            
            echo "${CANCER}: Attempt #$ATTEMPT (for Output #$CURRENT_RESULT_NUM)..."

            # Run the command
            timeout 5m python3 scripts/run_simulator.py -w "$OUT_DIR" -n 2 -t 2 jobs/nvflare_job_template --datasource-version 2_1 > outputs/results.log
            
            EXIT_STATUS=$?
            
            if [ $EXIT_STATUS -eq 0 ]; then
                # Verify the result file actually exists before counting it
                if [ -f "$RESULT_FILE" ]; then
                    RESULT_FILES+=("$RESULT_FILE")
                    ((SUCCESS_COUNT++))
                    python3 scripts/_parse_results.py outputs/results.log
                else
                    echo "WARNING: Job succeeded but result file not found at: $RESULT_FILE"
                    # Decide here if you want to count this as a failure or success. 
                    # Currently treating as success but not adding to average list would be risky.
                    # Let's count it as success but warn.
                fi
            else
                # Handle Failure
                if [ $EXIT_STATUS -eq 124 ]; then
                    echo "Attempt #$ATTEMPT TIMED OUT after 5 minutes."
                else
                    echo "Attempt #$ATTEMPT FAILED with error code $EXIT_STATUS."
                fi
                
                # Clean up partial directory
                if [ -d "$OUT_DIR" ]; then
                    echo "Cleaning up partial directory: $OUT_DIR"
                    rm -rf "$OUT_DIR"
                fi
            fi

            # echo "----------------------------------------"
            ((ATTEMPT++))
        done
    else
        echo "Skipping experiment runs as per configuration."
    fi

    # 2. AGGREGATING RESULTS
    SERVER_FILES=()
    SITE_FILES=()
    MISSING_FILES=false

    # 1. Collect all expected file paths
    for (( i=1; i<=TARGET_SUCCESSFUL_RUNS; i++ )); do
        
        # Construct paths based on the deterministic directory structure
        S_PATH="${RUN_PREFIX}/stat_analytics_${i}/server/job-results/simulate_job/profile_summary.json"
        C_PATH="${RUN_PREFIX}/stat_analytics_${i}/site-1/job-results/simulate_job/profile_summary.json"

        # Verify existence (in case a previous run was deleted or incomplete)
        if [ -f "$S_PATH" ]; then
            SERVER_FILES+=("$S_PATH")
        else
            echo "Error: Missing expected file: $S_PATH"
            MISSING_FILES=true
        fi

        if [ -f "$C_PATH" ]; then
            SITE_FILES+=("$C_PATH")
        else
            echo "Error: Missing expected file: $C_PATH"
            MISSING_FILES=true
        fi
    done

    # 2. Run Aggregation if all files are present
    if [ "$MISSING_FILES" = false ]; then
        
        # Aggregate Server
        python3 scripts/_generate_aggregate_results.py "${SERVER_FILES[@]}"
        mv averaged_profile_summary.json "outputs/averaged_server_summary__${CANCER_SLUG}.json"

        # Aggregate Site-1
        python3 scripts/_generate_aggregate_results.py "${SITE_FILES[@]}"
        mv averaged_profile_summary.json "outputs/averaged_site_summary__${CANCER_SLUG}.json"
    else
        echo "Aggregation FAILED: One or more expected result files are missing."
        exit 1
    fi

    mkdir -p "${RUN_PREFIX}/csv"
    python3 scripts/_generate_csv_results.py "outputs/averaged_server_summary__${CANCER_SLUG}.json" "outputs/averaged_site_summary__${CANCER_SLUG}.json" --outdir "${RUN_PREFIX}/csv"
done
