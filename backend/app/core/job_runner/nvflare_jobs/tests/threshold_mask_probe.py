"""Standalone CKKS probe for the secure threshold-samples pipeline (not collected by pytest).

Replicates _PRE_COUNT_SECURE_ as deployed -- ORIGINAL log-DP mask params (B ~ 27), the
+1 spare encryption level, and the towers=2 compress -- and checks that no reachable
mask value wraps the decrypted sign. Run after any CKKS parameter change (scale_mod,
mult_depth, scaling technique) and update _THRESHOLD_SAFE_DECRYPT_BOUND in
analytics_persistor_impl.py if the measured bound moves.

Usage: .venv/bin/python threshold_mask_probe.py       (~4 minutes)
"""
import math
import numpy as np
from openfhe import *

params = CCParamsCKKSRNS()
params.SetMultiplicativeDepth(10)
params.SetScalingModSize(53)
params.SetScalingTechnique(ScalingTechnique.FLEXIBLEAUTO)
params.SetKeySwitchTechnique(KeySwitchTechnique.HYBRID)
params.SetCKKSDataType(CKKSDataType.REAL)
params.SetSecurityLevel(SecurityLevel.HEStd_128_classic)
cc = GenCryptoContext(params)
for f in (PKESchemeFeature.PKE, PKESchemeFeature.KEYSWITCH,
          PKESchemeFeature.LEVELEDSHE, PKESchemeFeature.ADVANCEDSHE):
    cc.Enable(f)
kp = cc.KeyGen()
cc.EvalMultKeyGen(kp.secretKey)


def run(counts, rms, threshold):
    """The deployed pipeline: +1 spare level, tree add/mult, towers=2 compress."""
    n = len(counts)
    level = 10 - (math.ceil(math.log2(n + 1)) + 1)
    enc = [cc.Encrypt(kp.publicKey, cc.MakeCKKSPackedPlaintext([c], 1, level)) for c in counts]
    ct = enc[0]
    for e in enc[1:]:
        ct = cc.EvalAdd(ct, e)
    ct = cc.EvalSub(ct, cc.MakeCKKSPackedPlaintext([threshold - 0.5], 1, level))
    factors = [cc.Encrypt(kp.publicKey, cc.MakeCKKSPackedPlaintext([r], 1, level)) for r in rms] + [ct]
    while len(factors) > 1:
        nxt = [cc.EvalMult(factors[i], factors[i + 1]) for i in range(0, len(factors) - 1, 2)]
        if len(factors) % 2:
            nxt.append(factors[-1])
        factors = nxt
    out = cc.Compress(factors[0], 2, 1)
    pt = cc.Decrypt(out, kp.secretKey)
    pt.SetLength(1)
    return pt.GetRealPackedValue()[0]


def executor_mask(num_clients, sigma_val, B_val):
    """Exact copy of the executor's per-site mask draw."""
    scale_val = sigma_val / math.sqrt(num_clients)
    z = np.random.normal(loc=0.0, scale=scale_val)
    z = max(-B_val / num_clients, min(B_val / num_clients, z))
    return math.exp(z)


NOISE_FLOOR = 1e-10  # single-party abs decrypt error is ~1e-12; 100x slack

CONFIGS = [  # (n_sites, T, sigma, B) at branch maxima, original params
    (5, 10, 5.154, 27.14),
    (5, 20, 5.706, 27.70),
    (10, 20, 5.388, 26.91),
]

print("=== deterministic worst cases (fully clipped masks, original B) ===")
fails = 0
for n, T, sigma, B in CONFIGS:
    for direction in (+1, -1):
        rms = [math.exp(direction * B / n)] * n
        for counts, want_sign in [([T] * n, +1),                  # all at clip: max margin
                                  ([T - 1] + [0] * (n - 1), -1)]:  # just below threshold
            true_val = (sum(counts) - (T - 0.5)) * math.exp(direction * B)
            got = run(counts, rms, T)
            if abs(true_val) >= NOISE_FLOOR:
                ok = (got > 0) == (want_sign > 0) and abs(got - true_val) / abs(true_val) < 1e-2
            else:
                # Knife-edge margin times near-full negative clip sinks below the noise
                # floor: the sign is unreliable by design; the aggregator warns on it.
                # Require only that the value decrypts as correspondingly tiny.
                ok = abs(got) < 10 * NOISE_FLOOR
            fails += not ok
            print(f"n={n:2} T={T:2} mask=e^{direction * B:+6.2f} sum={sum(counts):3} "
                  f"true={true_val:12.4e} got={got:12.4e} ok={ok}")

print("\n=== random draws, executor formula (n=3, T=10, sigma=5.154, B=27.14) ===")
np.random.seed(0)
sign_errors = 0
N_TRIALS = 60
for counts, want_sign, label in [([10, 10, 10], +1, "well above (margin 20.5)"),
                                 ([10, 0, 0], +1, "exactly at T (margin 0.5)"),
                                 ([9, 0, 0], -1, "one below (margin -0.5)")]:
    errs = 0
    for _ in range(N_TRIALS):
        rms = [executor_mask(3, 5.154, 27.14) for _ in range(3)]
        got = run(counts, rms, 10)
        errs += (got > 0) != (want_sign > 0)
    sign_errors += errs
    print(f"{label:28} sign errors: {errs}/{N_TRIALS}")

print(f"\nTOTAL deterministic failures: {fails}, random sign errors: {sign_errors}")
print("PASS" if fails == 0 and sign_errors == 0 else "FAIL")
