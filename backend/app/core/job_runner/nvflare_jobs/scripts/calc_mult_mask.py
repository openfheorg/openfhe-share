import numpy as np

def calculate_parameters(n, epsilon, delta_power=-20, c=0.05, limit_bit=40):
    # User Constants
    T = 0.1307901367
    min_val = -0.4095066221
    
    # 1. Calculate Sensitivity
    # Max magnitude is driven by the negative lower bound
    s_double_prime_max = abs(n * min_val - T - c)
    s_double_prime_min = c
    
    delta_ln = np.log(s_double_prime_max / s_double_prime_min)
    
    # 2. Calculate Sigma (Standard Deviation)
    delta = 2**delta_power
    sigma = (delta_ln * np.sqrt(2 * np.log(1.25 / delta))) / epsilon
    
    # 3. Calculate B (Clipping Bound)
    B = sigma * np.sqrt(2 * np.log(1 / delta))
    
    # 4. Validation
    B_limit = np.log(2**limit_bit) # approx 27.7 for 40 bits
    
    print(f"--- Results for n={n} ---")
    print(f"Sensitivity (Delta_ln): {delta_ln:.4f}")
    print(f"Sigma (σ):              {sigma:.5f}")
    print(f"Clipping Bound (B):     {B:.5f}")
    print(f"Overflow Limit:         {B_limit:.2f}")
    
    if B <= B_limit:
        print("VALID: Parameters prevent overflow.")
    else:
        print("INVALID: B exceeds limit. Increase Epsilon or c.")

# Run with your estimated number of clients
calculate_parameters(n=5, epsilon=6.0, c=0.05)
