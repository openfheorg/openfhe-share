from .utils import (
    log_tree_op,
    average_model_dict,
    multiplicative_mask,
    additive_mask,
    load_weights_dataframe,
    biomarker_server_risk_key,
    ENC_BIOMARKER_SCORE_POSTPROCESS,
    ENC_BIOMARKER_RISK_GROUP_POSTPROCESS,
    ENC_BIOMARKER_DOT_PRODUCT_TYPES,
    ENC_BIOMARKER_DECRYPT_TYPES,
    ENC_BIOMARKER_SKIP_CUTOFF_TYPES,
)
import numpy as np
import logging
import math
from openfhe import (
    CCParamsCKKSRNS, ScalingTechnique, KeySwitchTechnique, CKKSDataType, SecurityLevel,
    GenCryptoContext, PKE, KEYSWITCH, LEVELEDSHE, ADVANCEDSHE, MULTIPARTY,
    Serialize, BINARY, DeserializeCryptoContextString, DeserializePublicKeyString,
    DeserializePrivateKeyString, DeserializeEvalKeyString, DeserializeEvalKeyMapString,
    DeserializeCiphertextString
)

from . import fhe_timing

# Time OpenFHE itself, not just the phases wrapped around it. Rebinding the free
# functions here covers every existing call site in this module without touching one
# of them, and the wrappers unwrap a timed CryptoContext defensively so passing one
# to Serialize still works.
fhe_timing.wrap_module_callables(globals(), (
    "GenCryptoContext", "Serialize",
    "DeserializeCryptoContextString", "DeserializePublicKeyString",
    "DeserializePrivateKeyString", "DeserializeEvalKeyString",
    "DeserializeEvalKeyMapString", "DeserializeCiphertextString",
), prefix="fhe.")
import concurrent.futures
import multiprocessing
import pickle
import time
import threading
from collections import OrderedDict
from multiprocessing import shared_memory
import os
from typing import Optional

# op_two_cipher_list operator -> CryptoContext method name. Resolved per call against self.cc (which is
# only set after initialize_openfhe); module-level so the table isn't rebuilt on every aggregation call.
_OP_FN_NAMES = {"add": "EvalAdd", "sub": "EvalSub", "mult": "EvalMult", "evalsum": "EvalSum"}

def _coerce_float_scalar(value, label: str = "value") -> float:
    """Coerce a scalar-like value into a float with a useful error message.

    Model cutoff values may arrive as numpy scalars, one-cell pandas objects,
    one-item lists, or numeric strings depending on how the cutoff CSV was read.
    Normalize them before using numeric operations such as abs() or CKKS packing.
    """
    # Pandas DataFrame/Series support without importing pandas into this module.
    if hasattr(value, "to_numpy"):
        arr = value.to_numpy().reshape(-1)
        arr = [v for v in arr if not (isinstance(v, float) and math.isnan(v))]
        if len(arr) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(arr)} values"
            )
        value = arr[0]

    while isinstance(value, (list, tuple, np.ndarray)):
        if len(value) != 1:
            raise ValueError(
                f"{label} must contain exactly one numeric value; found {len(value)} values"
            )
        value = value[0]

    if isinstance(value, str):
        value = value.replace("\ufeff", "").strip()
        if not value:
            raise ValueError(f"{label} cannot be blank")

    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be numeric, got {value!r}") from e


class OpenfheManager:
    # ``cc`` deliberately returns the RAW CryptoContext: other modules read it and hand
    # it straight to pybind11 (HEPersistor does ``Serialize(manager.cc, ...)``), where a
    # proxy would be rejected. ``_cct`` is the timed facade used only inside this module;
    # the setter keeps the two in step.
    @property
    def cc(self):
        return self._cc

    @cc.setter
    def cc(self, value):
        self._cc = value
        self._cct = fhe_timing.TimedProxy(value, "cc.") if value is not None else None

    def __init__(
        self,
        mult_depth=0,
        cc_batch_size=None,
        scale_mod_size=53,
        scaling_technique="FLEXIBLEAUTO",
        key_switch_technique="BV",
        ckks_data_type="REAL",
        generate_mult_keys: bool = False,
        generate_sum_keys: bool = False,
        generate_index_keys: bool = False,
        indices: Optional[list] = None,
        is_MultiParty=True,
        ring_dim=0
    ):
        '''Initializes the OpenFHE manager with CKKS parameters.

        This constructor sets up the configuration for creating a CKKS-based
        CryptoContext. The parameters control the trade-offs between security,
        performance, and the complexity of homomorphic operations supported.

        Args:
            mult_depth (int): The multiplicative depth for the CKKS scheme.
            cc_batch_size (int): The batch size for the CryptoContext, determining
                                 how many values can be packed into a ciphertext.
            scale_mod_size (int): The bit-length of the scaling factor.
            scaling_technique (str): The scaling technique to use (e.g., "FLEXIBLEAUTO").
            key_switch_technique (str): The key switching technique (e.g., "BV").
            ckks_data_type (str): The data type for CKKS operations ("REAL" or "COMPLEX").
            generate_mult_keys (bool): If True, generate evaluation keys for multiplication.
            generate_sum_keys (bool): If True, generate evaluation keys for summations.
            generate_index_keys (bool): If True, generate evaluation keys for rotations.
            indices (list): A list of indices required for rotation (EvalAtIndex) keys.
            is_MultiParty (bool): If True, enables multi-party (MPC) features.
            ring_dim (int): TEST/DEVELOPMENT ONLY. 0 (the default, and the only production
                value) lets OpenFHE derive the ring dimension from the 128-bit security
                level. Any positive value pins the ring dimension and DISABLES the security
                guarantee -- see initialize_openfhe. Falls back to the
                DUALITY_SIM_CKKS_RING_DIM environment variable when not passed explicitly,
                so the NVFlare simulator can shrink it for every party at once.
        '''
        self.mult_depth = mult_depth
        self.cc_batch_size = cc_batch_size
        self.scale_mod_size = scale_mod_size
        self.scaling_technique = scaling_technique
        self.key_switch_technique = key_switch_technique
        self.ckks_data_type = ckks_data_type
        self.generate_mult_keys = generate_mult_keys
        self.generate_sum_keys = generate_sum_keys
        self.generate_index_keys = generate_index_keys
        self.indices = list(indices) if indices else []
        self.is_MultiParty = is_MultiParty
        # 0 => derive from the security level (production). The env fallback exists so the
        # simulator can shrink the ring for the server and every client in one place; the
        # variable is absent in production deployments.
        self.ring_dim = int(ring_dim or os.environ.get("DUALITY_SIM_CKKS_RING_DIM", 0) or 0)

        self.cc = None
        self.kp = None
        self.evalMultKey = None
        self.evalSumKeys = None
        self.evalAtIndexKeys = None

        self.mp_public_key = None
        self.secret_key = None
        self.custom_logger = logging.getLogger("custom.audit_log")

        # Per-model random masks for biomarker_enc_risk_group_computation (masked multiparty decrypt).
        self.biomarker_decrypt_masks = {}  # model_key -> mask ciphertext

        # encrypted patient-covariate cache.
        self._cpatients_cache = OrderedDict()
        self._cpatients_cache_lock = threading.Lock()
        self._cpatients_cache_max = 2

    def initialize_openfhe(self):
        '''Initializes the OpenFHE CryptoContext based on the configured parameters.'''
        parameters = CCParamsCKKSRNS()
        parameters.SetMultiplicativeDepth(self.mult_depth)
        parameters.SetScalingModSize(self.scale_mod_size)
        if self.cc_batch_size is not None:
            parameters.SetBatchSize(self.cc_batch_size)
        parameters.SetScalingTechnique(getattr(ScalingTechnique, self.scaling_technique))
        parameters.SetKeySwitchTechnique(getattr(KeySwitchTechnique, self.key_switch_technique))
        parameters.SetCKKSDataType(getattr(CKKSDataType, self.ckks_data_type))

        # Production pins the 128-bit level explicitly and lets OpenFHE choose the ring
        # dimension (the same context the library default would produce). A pinned ring
        # dimension is only accepted with the security level unset, so the two always move
        # together and an under-sized ring can never be requested at full security.
        if self.ring_dim:
            parameters.SetSecurityLevel(SecurityLevel.HEStd_NotSet)
            parameters.SetRingDim(self.ring_dim)
            self.custom_logger.warning(
                "INSECURE CKKS parameters: ring dimension pinned to %s with security level "
                "HEStd_NotSet (DUALITY_SIM_CKKS_RING_DIM / ring_dim). Test and development "
                "use only -- never for production data.",
                self.ring_dim,
            )
        else:
            parameters.SetSecurityLevel(SecurityLevel.HEStd_128_classic)

        self.cc = GenCryptoContext(parameters)
        self._cct.Enable(PKE)
        self._cct.Enable(KEYSWITCH)
        self._cct.Enable(LEVELEDSHE)
        self._cct.Enable(ADVANCEDSHE)
        if self.is_MultiParty:
            self._cct.Enable(MULTIPARTY)

        if self.cc_batch_size is None:
            self.cc_batch_size = self._cct.GetBatchSize()

        audit = {
            "security_level": parameters.GetSecurityLevel().name,
            "ring_dimension": self._cct.GetRingDimension(),
            "batch_size": self._cct.GetBatchSize(),
            "scale_mod_size": parameters.GetScalingModSize(),
            "multiplicative_depth": self._cct.GetMultiplicativeDepth(),
            "scaling_technique": self._cct.GetScalingTechnique().name,
            "keyswitch_technique": self._cct.GetKeySwitchTechnique().name,
            "ckks_data_type": self._cct.GetCKKSDataType().name,
            "ind_cpa_noise_bits": 20,
        }

        raw_text = (
            "CryptoContext created with the following parameters:\n"
            f"            - Security Level:       {audit['security_level']}\n"
            f"            - Ring Dimension:       {audit['ring_dimension']}\n"
            f"            - Batch Size:           {audit['batch_size']}\n"
            f"            - Scale Mod Size:       {audit['scale_mod_size']}\n"
            f"            - Multiplicative Depth: {audit['multiplicative_depth']}\n"
            f"            - Scaling Technique:    {audit['scaling_technique']}\n"
            f"            - KeySwitch Technique:  {audit['keyswitch_technique']}\n"
            f"            - CKKS Data Type:       {audit['ckks_data_type']}\n"
            f"            IND-CPA^D noise flooding bits =  {audit['ind_cpa_noise_bits']} bits (default)."
        )
        self.crypto_audit_log = audit
        self.custom_logger.info(raw_text.strip())

    def get_audit_record(self) -> dict:
        return self.crypto_audit_log


    def keygen(self):
        '''Generates a key pair and evaluation keys based on the instance configuration.

        This should be called after `initialize_openfhe`. It creates the secret/public
        key pair and, if configured, the evaluation keys for multiplication,
        summation, and rotations.
        '''
        if self.cc is None:
            raise Exception("CryptoContext not initialized. Call initialize_openfhe() first.")
        self.kp = self._cct.KeyGen()
        self.custom_logger.info("KeyGen called for generating key pair.")
        if self.generate_mult_keys:
            self.evalMultKey = self._cct.KeySwitchGen(self.kp.secretKey, self.kp.secretKey)
            self.custom_logger.info("KeySwitchGen called for generating mult keys.")
        if self.generate_sum_keys:
            self._cct.EvalSumKeyGen(self.kp.secretKey)
            self.evalSumKeys = self._cct.GetEvalSumKeyMap(self.kp.secretKey.GetKeyTag())
            self.custom_logger.info("GetEvalSumKeyMap called for generating sum keys.")
        if self.generate_index_keys:
            self._cct.EvalAtIndexKeyGen(self.kp.secretKey, self.indices)
            self.evalAtIndexKeys = self._cct.GetEvalAutomorphismKeyMap(self.kp.secretKey.GetKeyTag())
            self.custom_logger.info(f"GetEvalAutomorphismKeyMap called for generating index keys at indices {self.indices}.")
        return

    # ---------------------------------------------------------------------------------
    # Helper Functions
    # ---------------------------------------------------------------------------------

    def serialize_cc(self) -> bytes:
        '''Serializes the CryptoContext to bytes.'''
        if self.cc is None:
            raise Exception("CryptoContext not initialized")
        return Serialize(self.cc, BINARY)

    def deserialize_cc(self, cc_bytes: bytes):
        '''Deserializes bytes into the instance's CryptoContext.'''
        self.cc = DeserializeCryptoContextString(cc_bytes, BINARY)
        return self.cc

    def serialize_public_key(self, pk=None) -> bytes:
        '''Serializes a public key to bytes. Uses the instance's key by default.'''
        if pk is None:
            pk = self.kp.publicKey
        return Serialize(pk, BINARY)

    def deserialize_public_key(self, pk_bytes: bytes):
        '''Deserializes bytes into a public key object.'''
        return DeserializePublicKeyString(pk_bytes, BINARY)

    def serialize_secret_key(self, sk=None) -> bytes:
        '''Serializes a secret key to bytes. Uses the instance's key by default.'''
        if sk is None:
            sk = self.kp.secretKey
        return Serialize(sk, BINARY)

    def deserialize_secret_key(self, sk_bytes: bytes):
        '''Deserializes bytes into a secret key object.'''
        return DeserializePrivateKeyString(sk_bytes, BINARY)

    def serialize_dict(self):
        '''Serializes the core crypto components into a dictionary of bytes.

        This is useful for packaging all necessary materials (CryptoContext, public key,
        and evaluation keys) to be sent to another party.
        '''
        if self.cc is None or self.kp is None:
            raise Exception("CryptoContext or KeyPair not initialized")
        payload = {
            "CC": Serialize(self.cc, BINARY),
            "pk": Serialize(self.kp.publicKey, BINARY),
            "batchSize": self.cc_batch_size
        }
        if self.generate_mult_keys:
            payload["evalMultKey"] = Serialize(self.evalMultKey, BINARY)
        if self.generate_sum_keys:
            payload["evalSumKeys"] = Serialize(self.evalSumKeys, BINARY)
        if self.generate_index_keys:
            payload["indices"] = self.indices
            payload["evalAtIndexKeys"] = Serialize(self.evalAtIndexKeys, BINARY)

        return payload

    def encrypt_batched_list(self, batched_list, level_val = 0):
        """Encrypts a list of vectors, where each vector is a batch.

        It packs each vector for complex CKKS, encrypts it with the multi-party
        public key, and returns a list of serialized ciphertexts.

        Args:
            batched_list (list[list[float]]): A list of vectors to encrypt.
            level_val (int): The level value for the plaintext.
        Returns:
            list[bytes]: A list of serialized ciphertexts.
        """
        encrypted_weights = []
        is_complex = self.ckks_data_type == "COMPLEX"
        for vec in batched_list:
            if is_complex:
                vec = PackFullComplex(vec, self.cc_batch_size)
            plaintext = self._cct.MakeCKKSPackedPlaintext(vec, level = level_val)
            enc_param = self._cct.Encrypt(self.mp_public_key, plaintext)
            encrypted_weights.append(Serialize(enc_param, BINARY))
        return encrypted_weights

    def encrypt_list(self, list_values, level_val = 0):
        """Encrypts a flat list of values.

        It automatically batches the list, packs each batch for complex CKKS,
        encrypts it, and returns a list of serialized ciphertexts.

        Args:
            list_values (list[float]): A flat list of values to encrypt.
            level_val (int): The level value for the plaintext.
        Returns:
            list[bytes]: A list of serialized ciphertexts.
        """
        encrypted_weights = []
        is_complex = self.ckks_data_type == "COMPLEX"
        for start in range(0, len(list_values), self.cc_batch_size):
            vec = list_values[start:start + self.cc_batch_size]
            if is_complex:
                vec = PackFullComplex(vec, self.cc_batch_size)
            plaintext = self._cct.MakeCKKSPackedPlaintext(vec, level = level_val)
            enc_param = self._cct.Encrypt(self.mp_public_key, plaintext)
            encrypted_weights.append(Serialize(enc_param, BINARY))
        return encrypted_weights

    def encrypt_biomarker_model(self, coeffs_df, cutoff_value, covs, level_val, for_scoring=False, lcs_only=False):
        """Pack and encrypt one biomarker model under the multiparty public key.

        Run by the *leader client* during ``workflow_model_upload`` so the plaintext model
        coefficients/cutoff never reach the server. The produced ciphertexts are at the same CKKS
        ``level_val`` the clients use to encrypt patient covariates, so the downstream homomorphic
        risk-score computation is level-matched.

        Coefficients and cutoff are baked at ``rsf = 1/|cutoff|`` so the encrypted dot product comes
        out at ``rsf*score`` (identical for KM discovery and LCS scoring, hence shareable). Baking
        keeps the signal large DURING the dot product, which the KM sign resolution needs -- a raw or
        partially-scaled cache is too noisy for near-zero cutoffs (measured; see the
        reuse-scores-neutral-cache-depth memory for the full exploration). ``for_scoring`` additionally
        emits the encrypted ``1/rsf`` (= |cutoff|) so the LCS path recovers the raw score by a
        homomorphic ``ct x ct`` descale and the server never needs the plaintext ``rsf``/``|cutoff|``.

        Args:
            coeffs_df: DataFrame with ``covariate`` and ``coef`` columns.
            cutoff_value (float): the model's scalar cutoff.
            covs (list[str]): the global biomarker covariate ordering (from the global schema).
            level_val (int): ``mult_depth - depth_required``.
            for_scoring (bool): selects the LCS scoring variant (``_score`` files + ER_threshold
                sidecar + the encrypted ``1/rsf`` descale ciphertext).
            lcs_only (bool): set when the job runs LCS with NO KM consumer. The rsf baking exists
                solely for KM's sign resolution, so an LCS-only job uploads at ``rsf = 1`` (raw
                score, no baking) and emits NO ``1/rsf`` ciphertext -- the LCS postprocess then
                skips the descale entirely, avoiding the near-zero-cutoff (large-rsf) round-trip
                precision loss. Ignored when a KM consumer shares the cache (must bake).
        Returns:
            tuple(bytes, bytes, bytes|None, float): ``(ser_coeff_ct, ser_cutoff_ct, ser_inv_rsf_ct, rsf)``
            with ``rsf = 1/|cutoff|`` (or ``1.0`` when cutoff is 0, or ``1.0`` when ``lcs_only``).
            ``ser_inv_rsf_ct`` (= |cutoff|) is produced ONLY when ``for_scoring and not lcs_only``
            (``None`` otherwise).
        """
        cutoff_value = _coerce_float_scalar(cutoff_value, "biomarker model cutoff")

        cov_length = len(covs)
        cov_length = 2 ** (math.ceil(math.log2(cov_length)))  # Round cov_length to next power of 2

        patients_per_batch = self.cc_batch_size // cov_length
        if patients_per_batch < 1:
            raise ValueError("Error: Our assumption that batch_size >= cov_length is violated.")

        from .fhir.filter_engine_config import align_model_coefficients

        coef_pen = coeffs_df.set_index("covariate")
        try:
            full_coeffs, _, _ = align_model_coefficients(
                coef_pen["coef"].to_dict(), covs, context_label="encrypt_biomarker_model"
            )
        except (TypeError, ValueError) as e:
            raise ValueError("biomarker model coefficients must be numeric") from e

        # rsf scales the coefficients (and cutoff) so the encrypted risk score comes out at
        # rsf*score. Both discovery (KM) and scoring (LCS) upload at this scale so the dot product
        # is identical and shareable; the LCS path recovers the raw score by a homomorphic multiply
        # with the encrypted 1/rsf (packed below).
        # LCS-only uploads raw (rsf=1): no KM consumer needs the baking, and skipping it lets the
        # LCS path avoid the 1/rsf descale round-trip (near-zero-cutoff precision loss).
        rsf = 1.0
        if not lcs_only and cutoff_value != 0:
            rsf = 1.0 / abs(cutoff_value)

        coeffs_list = [x * rsf for x in full_coeffs]
        if len(coeffs_list) < cov_length:
            coeffs_list.extend([0] * (cov_length - len(coeffs_list)))
        coeff_repeated = coeffs_list * patients_per_batch
        if len(coeff_repeated) < self.cc_batch_size:
            coeff_repeated.extend([0] * (self.cc_batch_size - len(coeff_repeated)))
        ptxt_coeff = self._cct.MakeCKKSPackedPlaintext(coeff_repeated, level=level_val)
        ctxt_coeff = self._cct.Encrypt(self.mp_public_key, ptxt_coeff)

        cutoff_repeated = [cutoff_value * rsf] * self.cc_batch_size
        ptxt_cutoff = self._cct.MakeCKKSPackedPlaintext(cutoff_repeated, level=level_val)
        ctxt_cutoff = self._cct.Encrypt(self.mp_public_key, ptxt_cutoff)

        # Encrypted reciprocal 1/rsf, produced ONLY for the LCS scoring upload: the scoring path
        # multiplies it into the packed rsf*score (ct x ct) to recover the raw score, so the server
        # never sees plaintext rsf / |cutoff|. Discovery leaves it unset (byte-for-byte unchanged).
        ser_inv_rsf = None
        if for_scoring and not lcs_only:
            inv_rsf_repeated = [1.0 / rsf] * self.cc_batch_size
            ptxt_inv_rsf = self._cct.MakeCKKSPackedPlaintext(inv_rsf_repeated, level=level_val)
            ser_inv_rsf = Serialize(self._cct.Encrypt(self.mp_public_key, ptxt_inv_rsf), BINARY)

        return Serialize(ctxt_coeff, BINARY), Serialize(ctxt_cutoff, BINARY), ser_inv_rsf, rsf

    def op_two_cipher_list(self, op, operand1, operand2):
        """Performs homomorphic operation of two lists (atleast one being list of ciphertexts).

        Args:
            op: Operator type. Supported are 'add', 'sub', 'mult', and 'evalsum'. Note: 'add' and 'sub' are done in-place.
            list1: List of ciphertexts, plaintexts, a single plaintext, or a scalar.
            list2: List of ciphertexts, plaintexts, a single plaintext, or a scalar.

        Returns:
            list: A new list of ciphertexts after function, defined by op, application.
        """
        if op not in _OP_FN_NAMES:
            raise ValueError(f"Unsupported operation: {op}. Supported operations are 'add', 'sub', 'mult', and 'evalsum'.")
        op_fn = getattr(self._cct, _OP_FN_NAMES[op])

        result_list = []
        if isinstance(operand1, list) and isinstance(operand2, list):
            if len(operand1) != len(operand2):  # TODO: Support operands of differing ciphertext-list lengths.
                raise ValueError(f"Ciphertext lists must be of the same length. Got {len(operand1)} and {len(operand2)}.")
            if op == "evalsum":
                raise ValueError("At least one argument a scalar representing batchsize.")
            for a, b in zip(operand1, operand2):
                result_list.append(op_fn(a, b))

        elif isinstance(operand1, list):
            # add/sub/mult -> op_fn(operand1[i], operand2); evalsum -> EvalSum(operand1[i], operand2)
            for a in operand1:
                result_list.append(op_fn(a, operand2))

        elif isinstance(operand2, list):
            if op == "evalsum":
                for i in range(len(operand2)):
                    result_list.append(self._cct.EvalSum(operand1[i], operand2))
            else:
                for b in operand2:
                    result_list.append(op_fn(operand1, b))
        else:
            raise ValueError("At least one argument must be a list of ciphers.")

        return result_list

    def zero_expected_value_mask(self, zeros_row, zeros_col):
        """Per-cell indicator for "this chi2 cell has a zero expected value".

        The chi2 expected value is ``row_marg * col_marg``, so a cell is degenerate when EITHER
        marginal is empty: the two indicators combine with OR (``zr + zc - zr*zc``), not AND. An
        AND only fires where a row and a column are both empty, which essentially never happens
        -- a filter that pins one variable to a single value leaves an empty column against
        populated rows, and those cells would go unguarded. Their denominator then stays zero,
        the ``ra_prime * denominator`` masking annihilates their shares of zero instead of
        carrying them, and the surviving shares no longer cancel, so the decrypted sum is a
        residual on the order of the additive-mask magnitude rather than a statistic.

        The ``zr*zc`` product is needed anyway to keep the result a true 0/1 indicator (so that
        ``1 - mask`` stays in {0,1}), and costs the same single multiplicative level the AND did.
        """
        both = self.op_two_cipher_list("mult", zeros_row, zeros_col)
        either = self.op_two_cipher_list("add", zeros_row, zeros_col)
        return self.op_two_cipher_list("sub", either, both)

    def op_compress_cipherlist(self, cipherlist, towers_to_keep, noiseScaleDeg = 1):
        """Compresses a list of ciphertexts to reduce their size before serialization.

        Dropping towers is lossy: if downstream decryption fails, raise towers_to_keep.

        Args:
            cipherlist (list[Ciphertext]): A list of ciphertexts to compress.
            towers_to_keep (int): The number of towers to remain after compression in each ciphertext.

        Returns:
            list[Ciphertext]: list of compressed ciphertexts.
        """
        compressed_cipherlist = []
        for cipher in cipherlist:
            compressed_cipherlist.append(self._cct.Compress(cipher, towers_to_keep, noiseScaleDeg))
        return compressed_cipherlist

    def OLD_decrypt_cipherlist(self, client_name, leader_client_name, arch, enc_result):  # TODO: Deprecate once the generic HE weight path moves to the stat-analytics decrypt variants.
        '''Generates a client's partial decryption share for a list of ciphertexts.

        1. Loads its local secret key.
        2. For each ciphertext in the input list, it computes its partial decryption share.
        3. Returns the list of serialized partial decryption shares to the server.
        '''
        list_partial_result = []
        for cipher in enc_result:
            cipher = DeserializeCiphertextString(cipher, BINARY)
            if arch == "cc" and client_name == leader_client_name:
                partial_result = self._cct.MultipartyDecryptLead([cipher], self.secret_key)   # in CC workflow, lead client is the lead decryptor.
            else:
                partial_result = self._cct.MultipartyDecryptMain([cipher], self.secret_key)
            list_partial_result.append(Serialize(partial_result[0], BINARY))

        self.custom_logger.info("Loaded aggregated encrypted result. Generating partial decryption shares and sending shares to server for fusion.")

        return {"partialresult": list_partial_result}

    def decrypt_all_partial_decrypts(self, partialshare_list):  # TODO: Deprecate once the generic HE weight path moves to the stat-analytics decrypt variants.
        '''Fuses partial decryption shares from all parties to get the final plaintext.

        This is typically run by a party that has collected all shares, such as the
        server or a designated result-recipient.

        Args:
            partialshare_list (list[list[bytes]]): A list where each inner list
                contains the partial decryption shares from one client.

        Returns:
            list[float]: The final, fully decrypted plaintext values as a flat list.
        '''
        list_result = []
        num_ciphertexts = len(partialshare_list[0])
        num_clients = len(partialshare_list)

        for i in range(num_ciphertexts):
            partialCiphertextVec = []
            for j in range(num_clients):
                partialresult = DeserializeCiphertextString(partialshare_list[j][i], BINARY)
                partialCiphertextVec.append(partialresult)
            # Combine partial shares to get the final plaintext
            plaintextMultipartyNew = self._cct.MultipartyDecryptFusion(partialCiphertextVec)
            if self.ckks_data_type == "COMPLEX":
                decoded_plaintext = UnpackFullComplex(plaintextMultipartyNew.GetCKKSPackedValue())
                list_result.extend(decoded_plaintext.tolist())
            else:
                decoded_plaintext = plaintextMultipartyNew.GetRealPackedValue()
                list_result.extend(decoded_plaintext)
        return list_result

    def OLD_decrypt_singlekey_cipherlist(self, enc_result):  # TODO: Deprecate once the generic HE weight path moves to the stat-analytics decrypt variants.
        '''Decrypts a list of ciphertexts using a single, non-multi-party secret key.

        Args:
            enc_result (list[bytes]): A list of serialized ciphertexts.

        Returns:
            list[float]: The decrypted plaintext values as a flat list.
        '''
        list_result = []
        for cipher in enc_result:
            cipher = DeserializeCiphertextString(cipher, BINARY)
            if self.ckks_data_type == "COMPLEX":
                decoded_plaintext = UnpackFullComplex(self._cct.Decrypt(cipher, self.secret_key).GetCKKSPackedValue())
                list_result.extend(decoded_plaintext.tolist())
            else:
                decoded_plaintext = self._cct.Decrypt(cipher, self.secret_key).GetRealPackedValue()
                list_result.extend(decoded_plaintext)
        return list_result

    def decrypt_cipherlist(self, cipherlist, arch, is_leader_client, decryptor_type = "main"):
        '''Generates a client's partial (or full) decryption for a list of ciphertexts, using single or multi-party key.'''
        list_result = []
        for cipher in cipherlist:
            if not self.is_MultiParty: # The calculated result here is the complete decryption.
                if self.ckks_data_type == "COMPLEX":
                    decoded_plaintext = UnpackFullComplex(self._cct.Decrypt(cipher, self.secret_key).GetCKKSPackedValue())
                    list_result.extend(decoded_plaintext.tolist())
                else:
                    decoded_plaintext = self._cct.Decrypt(cipher, self.secret_key).GetRealPackedValue()
                    list_result.extend(decoded_plaintext)
            else:
                if arch == "cc" and is_leader_client:
                    result = self._cct.MultipartyDecryptLead([cipher], self.secret_key)   # in CC workflow, lead client is the lead decryptor.
                else:
                    if decryptor_type == "lead":
                        result = self._cct.MultipartyDecryptLead([cipher], self.secret_key)
                    else:
                        result = self._cct.MultipartyDecryptMain([cipher], self.secret_key)
                list_result.append(result[0])
        return list_result


    # ---------------------------------------------------------------------------------
    # Server-Side (Aggregator) Functions
    # ---------------------------------------------------------------------------------
    def aggregate_keygen_star_round0(self, global_model, accepted_data, workspace_root, secret_key):
        '''Handles Round 0 of the Star-architecture multi-party key generation.

        This function, run by the server, aggregates key shares from all clients.
        1. Loads its own initial CryptoContext, public key, and secret key.
        2. Collects public key shares from all clients and adds them to create the
           joint multi-party public key (mpPK).
        3. Collects and aggregates evaluation key shares.
        4. Returns the aggregated public key and intermediate eval keys to be sent
           back to clients for the next round.
        5. Saves the mpPK and its own secret key for later use.
        '''
        # Load the CC and initial pk share of server
        self.cc = DeserializeCryptoContextString(global_model['weights']['CC'], BINARY)
        self.mp_public_key = DeserializePublicKeyString(global_model['weights']['pk'], BINARY)
        self.secret_key = secret_key
        self.mult_depth = global_model['meta']['mult_depth']
        self.cc_batch_size = global_model['meta']['cc_batch_size']
        self.ckks_data_type = global_model['meta']['ckks_data_type']

        # Aggregate the keys from all parties
        for value in accepted_data.values():
            pk_share = DeserializePublicKeyString(value.get("public_key_share"), BINARY)
            self.mp_public_key = self._cct.MultiAddPubKeys(self.mp_public_key, pk_share, pk_share.GetKeyTag())
        weights = {
            "public_key": Serialize(self.mp_public_key, BINARY)
        }
        if global_model['weights'].get('evalMultKey'):
            self.generate_mult_keys = True
            evalMultKey = DeserializeEvalKeyString(global_model['weights']['evalMultKey'], BINARY)
            evalMultAB = evalMultKey
            for value in accepted_data.values():
                evalMultKey2_share = DeserializeEvalKeyString(value.get("evalMultKey2"), BINARY)
                evalMultAB = self._cct.MultiAddEvalKeys(evalMultAB, evalMultKey2_share, pk_share.GetKeyTag())
            self.mp_evalMultKey = evalMultAB    # Temporary key stored in class member to save across rounds
            weights["evalMultAB"] = Serialize(evalMultAB, BINARY)
        if global_model['weights'].get('evalSumKeys'):
            self.generate_sum_keys = True
            evalSumKeys = DeserializeEvalKeyMapString(global_model['weights']["evalSumKeys"], BINARY)
            evalSumKeysJoin = evalSumKeys
            for value in accepted_data.values():
                evalSumKeysB_share = DeserializeEvalKeyMapString(value.get("evalSumKeysB"), BINARY)
                evalSumKeysJoin = self._cct.MultiAddEvalSumKeys(evalSumKeysJoin, evalSumKeysB_share, pk_share.GetKeyTag())
            self._cct.InsertEvalSumKey(evalSumKeysJoin)
        if global_model['weights'].get('evalAtIndexKeys'):
            self.generate_index_keys = True
            evalAtIndexKeys = DeserializeEvalKeyMapString(global_model['weights']["evalAtIndexKeys"], BINARY)
            self.indices = global_model['weights']["indices"]
            evalAtIndexKeysJoin = evalAtIndexKeys
            for value in accepted_data.values():
                evalAtIndexKeysB_share = DeserializeEvalKeyMapString(value.get("evalAtIndexKeysB"), BINARY)
                evalAtIndexKeysJoin = self._cct.MultiAddEvalAutomorphismKeys(evalAtIndexKeysJoin, evalAtIndexKeysB_share, pk_share.GetKeyTag())
            self._cct.InsertEvalAutomorphismKey(evalAtIndexKeysJoin)

        self.custom_logger.info(f"Aggregated key shares. Saving generated multi-party public key{f', sum key' if self.generate_sum_keys else ''}{f', index key' if self.generate_index_keys else ''}.")

        return weights

    def aggregate_keygen_star_round1(self, accepted_data):
        '''Handles Round 1 of the Star-architecture multi-party key generation.

        This function, run by the server, finalizes the evaluation keys.
        1. Receives the final evaluation key shares from all clients (e.g., evalMultBAB).
        2. Combines these shares with its own secret key and the intermediate keys
           from Round 0 to compute the final, complete evaluation keys.
        3. Inserts the final evaluation keys into its CryptoContext.
        4. Returns the final, fully-configured CryptoContext to be persisted.
        '''
        if self.generate_mult_keys:
            evalMultFinal = None
            if self.mp_evalMultKey:
                evalMultFinal = self._cct.MultiMultEvalKey(self.secret_key, self.mp_evalMultKey, self.mp_public_key.GetKeyTag())
            for value in accepted_data.values():
                evalMultBAB_share = DeserializeEvalKeyString(value.get("evalMultBAB"), BINARY)
                if evalMultFinal is None:
                    evalMultFinal = evalMultBAB_share
                else:
                    evalMultFinal = self._cct.MultiAddEvalMultKeys(evalMultFinal, evalMultBAB_share, self.mp_public_key.GetKeyTag())
            self._cct.InsertEvalMultKey([evalMultFinal])
            self.mp_evalMultKey = evalMultFinal
            self.custom_logger.info("Aggregated mult key shares. Saving generated mult key.")

        return Serialize(self.cc, BINARY)

    def aggregate_keygen_cc_round0(self, accepted_data, workspace_root):
        '''Handles Round 0 of the Client-contributed (CC) key generation.

        In this round, the server simply receives the initial crypto materials
        (CC, public key, eval keys) from the designated 'leader' client and
        broadcasts them to all other participating clients.
        '''
        # if debug:
        #     print("\n--- [DEBUG] Aggregator.aggregate_keygen_cc_round0 ---")
        #     print("Received initial CryptoContext and keys from the designated leader client.")
        #     print("Broadcasting materials to all other clients.")
        #     print("-----------------------------------------------------\n")
        self.custom_logger.info("Received initial CryptoContext and keys from the designated leader client. Broadcasting materials to all other clients.")

        for value in accepted_data.values():
            if "CC" in value:
                self.cc = DeserializeCryptoContextString(value.get('CC'), BINARY)
                if value.get('public_key_share') is None:
                    raise Exception("public_key_share not found in CC shareable")
                self.mp_public_key = DeserializePublicKeyString(value.get('public_key_share'), BINARY)    # Temporary key stored in class member to save across rounds. Same for below keys
                weights = {
                    "CC": value.get('CC'),
                    "public_key_share": value.get('public_key_share')
                }

                if value.get('evalMultKey'):
                    self.generate_mult_keys = True
                    self.mp_evalMultKey = DeserializeEvalKeyString(value.get('evalMultKey'), BINARY)
                    if not self.is_MultiParty:
                        self._cct.InsertEvalMultKey([self.mp_evalMultKey])
                    weights["evalMultKey"] = value.get('evalMultKey')
                if value.get('evalSumKeys'):
                    self.generate_sum_keys = True
                    self.mp_evalSumKeys = DeserializeEvalKeyMapString(value.get('evalSumKeys'), BINARY)
                    if not self.is_MultiParty:
                        self._cct.InsertEvalSumKey(self.mp_evalSumKeys)
                    weights["evalSumKeys"] = value.get("evalSumKeys")
                if value.get('evalAtIndexKeys'):
                    self.generate_index_keys = True
                    self.mp_evalAtIndexKeys = DeserializeEvalKeyMapString(value.get('evalAtIndexKeys'), BINARY)
                    self.indices = value.get("indices")
                    if not self.is_MultiParty:
                        self._cct.InsertEvalAutomorphismKey(self.mp_evalAtIndexKeys)
                    weights["evalAtIndexKeys"] = value.get("evalAtIndexKeys")
                    weights["indices"] = value.get("indices")

                return weights
        raise Exception("CryptoContext not initiated by the clients.")

    def aggregate_keygen_cc_round1(self, accepted_data, workspace_root):
        '''Handles Round 1 of the Client-contributed (CC) key generation.

        This round aggregates the key shares from the non-leader clients.
        1. Receives public key and evaluation key shares from all non-leader clients.
        2. Aggregates these shares with the leader's initial materials from Round 0
           to form the joint multi-party public key (mpPK) and intermediate eval keys.
        3. Returns the mpPK and intermediate keys to be sent to all clients for finalization.
        '''
        # if debug:
        #     print("\n--- [DEBUG] Aggregator.aggregate_keygen_cc_round1 ---")
        #     print("Received key shares from non-leader clients.")
        #     print("Aggregating shares to create joint public key and intermediate eval keys.")
        #     print("-----------------------------------------------------\n")
        self.custom_logger.info("Received key shares from non-leader clients. Aggregating shares to create joint public key and intermediate eval keys.")

        for value in accepted_data.values():
            pk_share = DeserializePublicKeyString(value.get("public_key_share"), BINARY)
            self.mp_public_key = self._cct.MultiAddPubKeys(self.mp_public_key, pk_share, pk_share.GetKeyTag())
        weights = {
            "public_key": Serialize(self.mp_public_key, BINARY)
        }
        if self.generate_mult_keys:
            evalMultAB = self.mp_evalMultKey
            for value in accepted_data.values():
                evalMultKey2_share = DeserializeEvalKeyString(value.get("evalMultKey2"), BINARY)
                evalMultAB = self._cct.MultiAddEvalKeys(evalMultAB, evalMultKey2_share, pk_share.GetKeyTag())
            self.mp_evalMultKey = None    # Intentionally set to None to reuse self._KeyGen_r1() function.
            weights["evalMultAB"] = Serialize(evalMultAB, BINARY)
        if self.generate_sum_keys:
            evalSumKeysJoin = self.mp_evalSumKeys
            for value in accepted_data.values():
                evalSumKeysB_share = DeserializeEvalKeyMapString(value.get("evalSumKeysB"), BINARY)
                evalSumKeysJoin = self._cct.MultiAddEvalSumKeys(evalSumKeysJoin, evalSumKeysB_share, pk_share.GetKeyTag())
            self.mp_evalSumKeys = evalSumKeysJoin
            self._cct.InsertEvalSumKey(evalSumKeysJoin)
        if self.generate_index_keys:
            evalAtIndexKeysJoin = self.mp_evalAtIndexKeys
            for value in accepted_data.values():
                evalAtIndexKeysB_share = DeserializeEvalKeyMapString(value.get("evalAtIndexKeysB"), BINARY)
                evalAtIndexKeysJoin = self._cct.MultiAddEvalAutomorphismKeys(evalAtIndexKeysJoin, evalAtIndexKeysB_share, pk_share.GetKeyTag())
            self.mp_evalAtIndexKeys = evalAtIndexKeysJoin
            self._cct.InsertEvalAutomorphismKey(evalAtIndexKeysJoin)

        # if debug:
        #     print("\n--- [DEBUG] Aggregator.aggregate_keygen_cc_round1 (Post-Aggregation) ---")
        #     print("Generated global public key and intermediate evaluation keys.")
        #     print("Sending joint public key and intermediate eval keys back to all clients.")
        #     print(f"Multi-party public key saved to: {workspace_root}/mp_public_key.bin")
        #     print("------------------------------------------------------------------------\n")
        self.custom_logger.info("Generated global public key and intermediate evaluation keys. Sending joint public key and intermediate eval keys back to all clients.")

        return weights


    def server_decrypt_round0(self, accepted_data, local_list_enc_result):  # TODO: Deprecate once the generic HE weight path moves to the stat-analytics decrypt variants.
        '''Handles the server-side portion of multi-party decryption.

        This function orchestrates the fusion of decryption shares from all parties.
        1. For each aggregated ciphertext, it computes its own partial decryption
           share using its secret key (`MultipartyDecryptLead`).
        2. It collects the partial decryption shares from all clients.
        3. It fuses its share with all client shares (`MultipartyDecryptFusion`) to
           reconstruct the final plaintext result.
        4. The plaintext is unpacked and returned as a flat list.
        '''
        list_result = []
        for i in range(len(local_list_enc_result)):
            localresult = local_list_enc_result[i]
            lead_partialresult = self._cct.MultipartyDecryptLead([localresult], self.secret_key)
            partialCiphertextVec = [lead_partialresult[0]]

            # Get partial decrypt shares from all parties
            for value in accepted_data.values():
                partialresult = DeserializeCiphertextString(value.get("partialresult")[i], BINARY)
                partialCiphertextVec.append(partialresult)

            # Combine partial shares to get the final plaintext
            plaintextMultipartyNew = self._cct.MultipartyDecryptFusion(partialCiphertextVec)
            if self.ckks_data_type == "COMPLEX":
                decoded_plaintext = UnpackFullComplex(plaintextMultipartyNew.GetCKKSPackedValue())
                list_result.append(decoded_plaintext.tolist())
            else:
                decoded_plaintext = plaintextMultipartyNew.GetRealPackedValue()
                list_result.append(decoded_plaintext)
        list_result = [item for sublist in list_result for item in sublist]

        return list_result


    def _combine_partial_decrypt_shares(self, partial_decrypt_shares, local_cipherlist = None):
        '''
        Arguments:
            local_cipherlist: list of ciphers.
            partial_decrypt_shares: dict, indexed by party name, carrying a list of cipher from each party (server/clients).
        Return:
            dec_cipherlist: list of fully decrypted values. (ciphers decrypted to lists are flattened)
        '''
        dec_cipherlist = []
        len_first_share = len(next(iter(partial_decrypt_shares.values())))
        for i in range(len_first_share):
            if local_cipherlist is not None:
                lead_partialresult = self._cct.MultipartyDecryptLead([local_cipherlist[i]], self.secret_key)
                partialCiphertextVec = [lead_partialresult[0]]
            else:
                partialCiphertextVec = []

            for client_share in partial_decrypt_shares.values():
                partialCiphertextVec.append(client_share[i])

            plaintextMultipartyNew = self._cct.MultipartyDecryptFusion(partialCiphertextVec)
            if self.ckks_data_type == "COMPLEX":
                decoded_plaintext = UnpackFullComplex(plaintextMultipartyNew.GetCKKSPackedValue())
                dec_cipherlist.extend(decoded_plaintext.tolist())
            else:
                decoded_plaintext = plaintextMultipartyNew.GetRealPackedValue()
                dec_cipherlist.extend(decoded_plaintext)
        return dec_cipherlist

    def _decrypt_stat_analytics_all_shares(self, computation_type, accepted_data, local_list_enc_result=None, arch="star", metadata={}):
        '''Call with local_list_enc_result as None if accepted_data contains partial_decryption share from server as well. local_list_enc_result is provided only when the final partial_decrypt_share aggregation happens at server side.'''
        self.custom_logger.info(f"Combining partial decryption shares from everyone and decrypting fully for computation_type = {computation_type}.")
        dec_result = {}

        if arch == "cc":
            if not self.is_MultiParty:
                return dec_result
            return accepted_data

        if computation_type == "_PRE_COUNT_UNSECURE_" or computation_type == "_PRE_COUNT_SECURE_":
            client_shares = {cn: deserialize_cipherlist(cd["partialresult"]) for cn, cd in accepted_data.items()}
            return self._combine_partial_decrypt_shares(client_shares, local_list_enc_result)

        elif computation_type == "mean":
            client_shares = {cn: deserialize_cipherlist(cd["partialresult"]) for cn, cd in accepted_data.items()}
            plaintext = self._combine_partial_decrypt_shares(client_shares, local_list_enc_result)
            dec_result["sum"] = plaintext[0]
            dec_result["count"] = plaintext[1]

        elif computation_type == "meta-analysis":
            client_shares = {cn: deserialize_cipherlist(cd["partialresult"]) for cn, cd in accepted_data.items()}
            plaintext = self._combine_partial_decrypt_shares(client_shares, local_list_enc_result)
            # No mask was applied; slot 0 = Σ w·β₁, slot 1 = Σ w, slot 2 = usable-site count.
            dec_result["sum"] = plaintext[0]
            dec_result["count"] = plaintext[1]
            dec_result["usable"] = plaintext[2]

        elif computation_type == "stdev":
            client_shares = {cn: deserialize_cipherlist(cd["partialresult"]) for cn, cd in accepted_data.items()}
            plaintext = self._combine_partial_decrypt_shares(client_shares, local_list_enc_result)
            dec_result["numerator"] = plaintext[0]
            dec_result["denominator"] = plaintext[2]

        elif computation_type == "mean-stdev":
            client_shares = {cn: deserialize_cipherlist(cd["partialresult"]) for cn, cd in accepted_data.items()}
            plaintext = self._combine_partial_decrypt_shares(client_shares, local_list_enc_result)
            # Slot layout after the rotate-multiply-subtract pipeline and
            # masking: slot 0 = r1·numerator_std, slot 2 = r1·denominator_std,
            # slot 5 = r2·sum (mean numerator), slot 7 = r2·count (mean denom).
            dec_result["numerator"] = plaintext[0]
            dec_result["denominator"] = plaintext[2]
            dec_result["sum"] = plaintext[5]
            dec_result["count"] = plaintext[7]

        elif computation_type == "chi2":
            client_shares = {
                "numerator": {},
                "denominator": {},
                "dof": {}
            }
            for client_name, client_data in accepted_data.items():
                client_shares["numerator"][client_name] = deserialize_cipherlist(client_data["partialresult"]["numerator"])
                client_shares["denominator"][client_name] = deserialize_cipherlist(client_data["partialresult"]["denominator"])
                client_shares["dof"][client_name] = deserialize_cipherlist(client_data["partialresult"]["dof"])

            # The aggregator scaled both dof factors by the broadcast widths, so their product
            # carries an extra len_category1*len_category2 -- divide it out and round back to the
            # integer it is. See the dof comment in the chi2 branch of the aggregation step.
            n_cells = metadata["len_category1"] * metadata["len_category2"]
            if local_list_enc_result is not None:
                dec_result["numerator"] = self._combine_partial_decrypt_shares(client_shares["numerator"], local_list_enc_result["numerator"])[:n_cells]
                dec_result["denominator"] = self._combine_partial_decrypt_shares(client_shares["denominator"], local_list_enc_result["denominator"])[:n_cells]
                dec_result["dof"] = round(self._combine_partial_decrypt_shares(client_shares["dof"], local_list_enc_result["dof"])[0] / n_cells)
            else:
                dec_result["numerator"] = self._combine_partial_decrypt_shares(client_shares["numerator"])[:n_cells]
                dec_result["denominator"] = self._combine_partial_decrypt_shares(client_shares["denominator"])[:n_cells]
                dec_result["dof"] = round(self._combine_partial_decrypt_shares(client_shares["dof"])[0] / n_cells)

        elif computation_type in ENC_BIOMARKER_DECRYPT_TYPES:
            # Each (model, risk_client) slice is a LIST of output ciphers (one per
            # cc_batch_size-wide window of that client's cohort); fuse them position-wise.
            model_keys = list(local_list_enc_result.keys())
            risk_clients = list(next(iter(local_list_enc_result.values())).keys())
            dec_result = {mk: {} for mk in model_keys}
            for mk in model_keys:
                for risk_client in risk_clients:
                    local_cts = _as_cipher_list(local_list_enc_result[mk][risk_client])
                    client_shares = {
                        party_name: deserialize_cipherlist(
                            _as_cipher_list(client_data["partialresult"][mk][risk_client])
                        )
                        for party_name, client_data in accepted_data.items()
                    }
                    for party_name, share in client_shares.items():
                        if len(share) != len(local_cts):
                            raise ValueError(
                                f"Biomarker decrypt share count mismatch for model_key={mk!r}, "
                                f"slice={risk_client!r}: {party_name} returned {len(share)} "
                                f"partial share(s) for {len(local_cts)} output cipher(s). All "
                                f"parties must partially decrypt every output cipher."
                            )
                    fused = []
                    for idx, local_ct in enumerate(local_cts):
                        lead_partial_share = self._cct.MultipartyDecryptLead(
                            [local_ct], self.secret_key
                        )[0]
                        for client_share in client_shares.values():
                            self._cct.EvalAddInPlace(lead_partial_share, client_share[idx])
                        fused.append(Serialize(lead_partial_share, BINARY))
                    dec_result[mk][risk_client] = fused

        elif computation_type == "kaplan-meier":
            sample_client = next(iter(accepted_data.values()), {})
            all_group_names = sorted(sample_client.get("partialresult", {}).get("numerator_groups", {}).keys())

            has_logrank = "numerator_A" in next(iter(accepted_data.values()), {}).get("partialresult", {})
            client_shares = {}
            client_shares["numerator_groups"] = {group: {} for group in all_group_names}
            client_shares["denominator_groups"] = {group: {} for group in all_group_names}
            if len(all_group_names) == 2 and has_logrank:
                client_shares["numerator_A"] = {}
                client_shares["denominator_A"] = {}
                client_shares["numerator_var_A"] = {}
                client_shares["denominator_var_A"] = {}

            dec_result["numerator_groups"] = {group: {} for group in all_group_names}
            dec_result["denominator_groups"] = {group: {} for group in all_group_names}
            if len(all_group_names) == 2 and has_logrank:
                dec_result["numerator_A"] = {}
                dec_result["denominator_A"] = {}
                dec_result["numerator_var_A"] = {}
                dec_result["denominator_var_A"] = {}

            for client_name, client_data in accepted_data.items():
                pr = client_data["partialresult"]
                for group in all_group_names:
                    client_shares["numerator_groups"][group][client_name] = deserialize_cipherlist(pr["numerator_groups"][group])
                    client_shares["denominator_groups"][group][client_name] = deserialize_cipherlist(pr["denominator_groups"][group])
                if len(all_group_names) == 2 and has_logrank:
                    client_shares["numerator_A"][client_name] = deserialize_cipherlist(pr["numerator_A"])
                    client_shares["denominator_A"][client_name] = deserialize_cipherlist(pr["denominator_A"])
                    client_shares["numerator_var_A"][client_name] = deserialize_cipherlist(pr["numerator_var_A"])
                    client_shares["denominator_var_A"][client_name] = deserialize_cipherlist(pr["denominator_var_A"])

            for group in all_group_names:
                if local_list_enc_result is not None:
                    dec_result["numerator_groups"][group] = self._combine_partial_decrypt_shares(client_shares["numerator_groups"][group], local_list_enc_result["numerator_groups"][group])[:metadata["len_time_grid"]]
                    dec_result["denominator_groups"][group] = self._combine_partial_decrypt_shares(client_shares["denominator_groups"][group], local_list_enc_result["denominator_groups"][group])[:metadata["len_time_grid"]]
                else:
                    dec_result["numerator_groups"][group] = self._combine_partial_decrypt_shares(client_shares["numerator_groups"][group])[:metadata["len_time_grid"]]
                    dec_result["denominator_groups"][group] = self._combine_partial_decrypt_shares(client_shares["denominator_groups"][group])[:metadata["len_time_grid"]]
            if len(all_group_names) == 2 and has_logrank:
                if local_list_enc_result is not None:
                    dec_result["numerator_A"] = self._combine_partial_decrypt_shares(client_shares["numerator_A"], local_list_enc_result["numerator_A"])[:metadata["len_time_grid"]]
                    dec_result["denominator_A"] = self._combine_partial_decrypt_shares(client_shares["denominator_A"], local_list_enc_result["denominator_A"])[:metadata["len_time_grid"]]
                    dec_result["numerator_var_A"] = self._combine_partial_decrypt_shares(client_shares["numerator_var_A"], local_list_enc_result["numerator_var_A"])[:metadata["len_time_grid"]]
                    dec_result["denominator_var_A"] = self._combine_partial_decrypt_shares(client_shares["denominator_var_A"], local_list_enc_result["denominator_var_A"])[:metadata["len_time_grid"]]
                else:
                    dec_result["numerator_A"] = self._combine_partial_decrypt_shares(client_shares["numerator_A"])[:metadata["len_time_grid"]]
                    dec_result["denominator_A"] = self._combine_partial_decrypt_shares(client_shares["denominator_A"])[:metadata["len_time_grid"]]
                    dec_result["numerator_var_A"] = self._combine_partial_decrypt_shares(client_shares["numerator_var_A"])[:metadata["len_time_grid"]]
                    dec_result["denominator_var_A"] = self._combine_partial_decrypt_shares(client_shares["denominator_var_A"])[:metadata["len_time_grid"]]

        elif computation_type == "t-test":
            client_shares = {
                "num_d": {},
                "num_den_d": {},
                "den_den_d": {},
                "num_t": {},
                "den_t": {}
            }
            for client_name, client_data in accepted_data.items():
                client_shares["num_d"][client_name] = deserialize_cipherlist(client_data["partialresult"]["num_d"])
                client_shares["num_den_d"][client_name] = deserialize_cipherlist(client_data["partialresult"]["num_den_d"])
                client_shares["den_den_d"][client_name] = deserialize_cipherlist(client_data["partialresult"]["den_den_d"])
                client_shares["num_t"][client_name] = deserialize_cipherlist(client_data["partialresult"]["num_t"])
                client_shares["den_t"][client_name] = deserialize_cipherlist(client_data["partialresult"]["den_t"])

            if local_list_enc_result is not None:
                dec_result["num_d"] = self._combine_partial_decrypt_shares(client_shares["num_d"], local_list_enc_result["num_d"])[0]
                dec_result["num_den_d"] = self._combine_partial_decrypt_shares(client_shares["num_den_d"], local_list_enc_result["num_den_d"])
                dec_result["num_den_d"] = [dec_result["num_den_d"][0], dec_result["num_den_d"][8]]
                dec_result["den_den_d"] = self._combine_partial_decrypt_shares(client_shares["den_den_d"], local_list_enc_result["den_den_d"])
                dec_result["den_den_d"] = [dec_result["den_den_d"][0], dec_result["den_den_d"][8]]
                dec_result["num_t"] = self._combine_partial_decrypt_shares(client_shares["num_t"], local_list_enc_result["num_t"])[0]
                dec_result["den_t"] = self._combine_partial_decrypt_shares(client_shares["den_t"], local_list_enc_result["den_t"])[0]
            else:
                dec_result["num_d"] = self._combine_partial_decrypt_shares(client_shares["num_d"])[0]
                dec_result["num_den_d"] = self._combine_partial_decrypt_shares(client_shares["num_den_d"])
                dec_result["num_den_d"] = [dec_result["num_den_d"][0], dec_result["num_den_d"][8]]
                dec_result["den_den_d"] = self._combine_partial_decrypt_shares(client_shares["den_den_d"])
                dec_result["den_den_d"] = [dec_result["den_den_d"][0], dec_result["den_den_d"][8]]
                dec_result["num_t"] = self._combine_partial_decrypt_shares(client_shares["num_t"])[0]
                dec_result["den_t"] = self._combine_partial_decrypt_shares(client_shares["den_t"])[0]

        return dec_result

    def server_decrypt_stat_analytics_r0(self, computation_type, accepted_data, local_list_enc_result, arch, metadata={}, hide_result_from_server=False):
        if hide_result_from_server:
            accepted_data["server"] = self._decrypt_stat_analytics_single_shares(computation_type, local_list_enc_result, arch, "server", False, decryptor_type = "lead")
            return accepted_data
        return self._decrypt_stat_analytics_all_shares(computation_type, accepted_data, local_list_enc_result, arch, metadata)

    def aggregate_net_weights(self, accepted_data):
        '''Performs homomorphic aggregation of encrypted model updates from clients.

        It collects encrypted "ciphertext" lists and (optional) "unencrypted_weights"
        from all clients. It then uses `log_tree_op` to homomorphically add the
        encrypted parts and plainly sum the unencrypted parts.

        Args:
            accepted_data (dict): Data received from all clients.
            round (int): The current round number.
            workflow (str): The name of the current workflow.
            workspace_root (str): Path to the workspace directory.

        Returns:
            A tuple containing:
            - payload (dict): A dictionary with the aggregated encrypted result
              ("enc_result") and averaged unencrypted weights.
            - local_list_enc_result (list): A list of deserialized aggregated ciphertexts.
        '''
        # if debug:
        #     print("\n--- [DEBUG] Aggregator.aggregate_net_weights ---")
        #     print(f"Aggregating weights from {len(accepted_data)} clients.")
        #     print("------------------------------------------------\n")

        # Aggregate the ciphertexts from all parties
        encrypted_party_data = []
        unencrypted_party_data = []
        for party_data in accepted_data.values():
            encrypted_party_data.append(party_data.get("ciphertext"))
            if "unencrypted_weights" in party_data:
                unencrypted_party_data.append(party_data["unencrypted_weights"])

        # Secure aggregation for encrypted layers
        local_list_enc_result = log_tree_op("add", deserialize_cipherlist(encrypted_party_data), is_encrypted=True, op_fn=self.op_two_cipher_list) # Locally saving the de-serialized result
        list_enc_result = serialize_cipherlist(local_list_enc_result)
        # Unencrypted aggregation for unencrypted layers
        if unencrypted_party_data:
            agg_unencrypted = log_tree_op("add", unencrypted_party_data, is_encrypted=False)
            agg_unencrypted = average_model_dict(agg_unencrypted, len(unencrypted_party_data))
        else:
            agg_unencrypted = None

        payload = {"enc_result": list_enc_result}
        if agg_unencrypted:
            payload["unencrypted_weights"] = agg_unencrypted

        return payload, local_list_enc_result

    @staticmethod
    def _biomarker_model_mask_params(num_clients):
        """(sigma, B) for the model-hiding multiplicative mask ``rm``, calibrated on the
        CLIENT count. Shared by the fused discovery dot product and the split KM postprocess
        tail so both stay on one calibration table. >10 clients is unsupported."""
        if num_clients <= 5:
            return 3.35890, 17.68643
        elif num_clients <= 10:
            return 3.93544, 20.72223
        raise ValueError("Error: More than 10 clients not supported currently for this computation.")

    def aggregate_stat_analytics(self, computation_type, accepted_data, local_analysed_data, metadata={}, depth_required = None):
        '''Performs encrypted aggregation for statistical analytics.

        This is the "Computing Party" role. It aggregates ciphertexts from clients
        and performs the requested homomorphic computation (e.g., mean, std).
        It also applies a random mask to the result before sending it for decryption.

        Args:
            computation_type (str): The type of computation ("mean" or "std").
            accepted_data (dict): Data received from all clients.

        Returns:
            A tuple containing the payload with the masked encrypted result and a
            local copy of the deserialized masked result.
        '''
        self.custom_logger.info(f"Aggregating for computation = {computation_type}")
        self.last_parallel_stats = None
        level_val = 0
        if depth_required:
            level_val = self.mult_depth - depth_required

        if computation_type == "_PRE_COUNT_UNSECURE_":
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data['count'], level = level_val))
            list_ciphers = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)

            local_list_enc_result = self.op_compress_cipherlist(list_ciphers, 1, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)

        elif computation_type == "_PRE_COUNT_SECURE_":
            client_lists_count = [deserialize_cipherlist(client_share.get("ciphertext")["count"]) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists_count.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data['count'], level = level_val))
            ctx_sum = log_tree_op("add", client_lists_count, is_encrypted=True, op_fn=self.op_two_cipher_list)

            const_noise = 0.5
            ctx_sum = self.op_two_cipher_list("sub", ctx_sum, self._cct.MakeCKKSPackedPlaintext([metadata["threshold"] - const_noise]*metadata["num_workflows"], level = level_val))
            self.custom_logger.info(f"Applied small noise < 1 to hide the case when total count = 0.")

            client_lists_rm = [deserialize_cipherlist(client_share.get("ciphertext")["rm_share"]) for client_share in accepted_data.values()]
            client_lists_rm.append(ctx_sum)
            local_list_enc_result = log_tree_op("mult", client_lists_rm, is_encrypted=True, op_fn=self.op_two_cipher_list)
            self.custom_logger.info(f"Applied multiplicative masks for each workflow.")

            # Keep 2 towers: the masked margin spans up to margin_max * e^B (~1e14) and a
            # single tower decodes correctly only up to ~2^(73 - scale_mod) (~1e6 at scale
            # 53), silently wrapping the sign at random beyond that. The clients encrypt
            # one level above the mult-tree need (depth_required has a +1 spare) so a
            # second tower survives to decryption, which is exact up to ~1e16 (measured).
            local_list_enc_result = self.op_compress_cipherlist(local_list_enc_result, 2, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)


        elif computation_type == "mean":
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists.append(self._cct.MakeCKKSPackedPlaintext([local_analysed_data['sum'], local_analysed_data['count']]+ [0] * (self.cc_batch_size - 2), level = level_val))
            list_ciphers = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)

            # Random masking
            if self.ckks_data_type == "REAL":
                r = abs(multiplicative_mask(loc=15.42, sigma=6.47))
                self.custom_logger.info(f"Applied multiplicative mask: loc = 15.42, sigma=6.47.")
            else:
                r = abs(multiplicative_mask())
                self.custom_logger.info(f"Applied multiplicative mask: loc = 19.42, sigma=5.22.")
            if metadata["global_count"] is not None:
                if metadata["global_count"] == 0:
                    raise ValueError("global_count cannot be zero.")
                r = r / (metadata["global_count"])
            mask_vec = [r, r] + [0] * (self.cc_batch_size - 2)
            plaintext_mask = self._cct.MakeCKKSPackedPlaintext(mask_vec, level = level_val)
            local_list_enc_result = self.op_two_cipher_list("mult", list_ciphers, plaintext_mask)   # Locally saving the de-serialized result

            local_list_enc_result = self.op_compress_cipherlist(local_list_enc_result, 2, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)

        elif computation_type == "meta-analysis":
            # Fixed-effects inverse-variance meta-analysis: pure tree-sum of the 3-slot per-client shares (w·β₁, w, usable). NO multiplicative
            # mask — the post-processing needs Σ wₖ in the clear (for the pooled SE = 1/√(Σ wₖ)) and the usable-site count for the >= 2 gate.
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists.append(self._cct.MakeCKKSPackedPlaintext(
                    [local_analysed_data['sum'], local_analysed_data['count'], local_analysed_data.get('usable', 0.0)]
                    + [0] * (self.cc_batch_size - 3),
                    level=level_val,
                ))
            list_ciphers = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)
            local_list_enc_result = list_ciphers

            local_list_enc_result = self.op_compress_cipherlist(local_list_enc_result, 1, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)

        elif computation_type == "stdev":
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists.append(self._cct.MakeCKKSPackedPlaintext([local_analysed_data['sum_sq'], local_analysed_data['sum'], local_analysed_data['count'], local_analysed_data['sum'], local_analysed_data['count']]+ [0] * (self.cc_batch_size - 5), level = level_val))

            # 1. Sum (in a recursive way).
            ctx = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)
            # 2. Rotate ctx by two positions to left. If ‘sample’, subtract [0, 0, 1, 0…]
            ctx_prime = [self._cct.EvalAtIndex(ctx[0], 2)]
            if metadata["std_type"] == "sample":
                self._cct.EvalSubInPlace(ctx_prime[0], self._cct.MakeCKKSPackedPlaintext([0, 0, 1] + [0] * (self.cc_batch_size - 3), level = level_val))
            # 3. Multiply ctx by ctx’
            ctx = self.op_two_cipher_list("mult", ctx, ctx_prime)
            # 4. Rotate ctx by one position to left.
            ctx_prime = [self._cct.EvalRotate(ctx[0], 1)]
            # 5. Subtract ctx’ from ctx in place.
            self._cct.EvalSubInPlace(ctx[0], ctx_prime[0])

            # Random masking
            if self.ckks_data_type == "REAL":
                r = abs(multiplicative_mask(loc=15.42, sigma=6.47))
                self.custom_logger.info(f"Applied multiplicative mask: loc = 15.42, sigma=6.47.")
            else:
                r = abs(multiplicative_mask())
                self.custom_logger.info(f"Applied multiplicative mask: loc = 19.42, sigma=5.22.")
            if metadata["global_count"] is not None:
                if metadata["global_count"] == 0:
                    raise ValueError("global_count cannot be zero.")
                r = r / (metadata["global_count"]**2)
            mask_vec = [r, 0, r] + [0] * (self.cc_batch_size - 3)
            plaintext_mask = self._cct.MakeCKKSPackedPlaintext(mask_vec, level = level_val)
            local_list_enc_result = self.op_two_cipher_list("mult", ctx, plaintext_mask)   # Locally saving the de-serialized result

            local_list_enc_result = self.op_compress_cipherlist(local_list_enc_result, 2, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)

        elif computation_type == "mean-stdev":
            # Combined mean + stdev in a single HE workload.
            # Per-client slot layout: [x²_sum, x_sum, n, x_sum, n, 0, x_sum, n, 0]
            #   - slots 0..4 carry the std payload (mirrors the stdev workflow)
            #   - slots 6..8 carry the duplicate (x_sum, n, 0) used for mean
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                client_lists.append(self._cct.MakeCKKSPackedPlaintext(
                    [local_analysed_data['sum_sq'], local_analysed_data['sum'], local_analysed_data['count'],
                     local_analysed_data['sum'], local_analysed_data['count'], 0,
                     local_analysed_data['sum'], local_analysed_data['count'], 0]
                    + [0] * (self.cc_batch_size - 9),
                    level=level_val,
                ))

            # 1. Sum (in a recursive way).
            ctx = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)

            # 2. Rotate ctx by two positions to the left. If 'sample', add [0, 0, -1, 0, 0, 0, 1, 1, 0,...]; otherwise
            # 'population' adds [0, 0, 0, 0, 0, 0, 1, 1, 0,...]. The +1s at slots 6,7 inject the mean payload before the multiply step.
            ctx_prime = [self._cct.EvalAtIndex(ctx[0], 2)]
            if metadata["std_type"] == "sample":
                add_vec = [0, 0, -1, 0, 0, 0, 1, 1, 0] + [0] * (self.cc_batch_size - 9)
            else:
                add_vec = [0, 0, 0, 0, 0, 0, 1, 1, 0] + [0] * (self.cc_batch_size - 9)
            self._cct.EvalAddInPlace(ctx_prime[0], self._cct.MakeCKKSPackedPlaintext(add_vec, level=level_val))

            # 3. Multiply ctx by ctx'.
            ctx = self.op_two_cipher_list("mult", ctx, ctx_prime)
            # 4. Rotate ctx by one position to the left.
            ctx_prime = [self._cct.EvalRotate(ctx[0], 1)]
            # 5. Subtract ctx' from ctx in place.
            self._cct.EvalSubInPlace(ctx[0], ctx_prime[0])

            # 6. Mask multiply: zero out unused slots and flip the slot-5 sign (slot 5 carries -x_sum after step 5). Apply independent
            #    log-normal multiplicative masks r1 (slots 0, 2) and r2 (slots 5, 7). The masks hide both the absolute scale of the
            #    sums and the global cohort size (slot 7 carries r2·n, which is not a recoverable plaintext).
            #    Two regimes:
            #    * Column-data mode (``global_count`` known): divide r1 by ``global_count²`` (slot 0/2 scale as n²) and r2 by
            #      ``global_count`` (slot 5/7 scale as n) so the masked ciphertext stays inside CKKS precision.
            #
            #    * Cached-scores mode (``global_count is None``, i.e. over_cached_scores): no precomputed ``n`` to scale by,
            #      so we use smaller log-normal parameters tuned so the masked slot values stay inside CKKS precision for the
            #      worst-case patient counts encountered in practice (~10⁴). r1 covers std slots (size ~ n²); r2 covers
            #      mean slots (size ~ n). Bands kept at the function default ±3σ for CKKS precision; σ is small enough that
            #      the Gaussian-mechanism δ stays ≤ 2⁻¹³ at the cost of a larger ε.
            if metadata["global_count"] is not None:
                if metadata["global_count"] == 0:
                    raise ValueError("global_count cannot be zero.")
                if self.ckks_data_type == "REAL":
                    r1 = abs(multiplicative_mask(loc=15.42, sigma=6.47))
                    r2 = abs(multiplicative_mask(loc=15.42, sigma=6.47))
                    self.custom_logger.info("Applied multiplicative masks (mean-stdev): loc = 15.42, sigma=6.47.")
                else:
                    r1 = abs(multiplicative_mask())
                    r2 = abs(multiplicative_mask())
                    self.custom_logger.info("Applied multiplicative masks (mean-stdev): loc = 19.42, sigma=5.22.")
                r1 = r1 / (metadata["global_count"] ** 2)
                r2 = r2 / metadata["global_count"]
            else:
                r1 = abs(multiplicative_mask(loc=8.0, sigma=1.5))
                r2 = abs(multiplicative_mask(loc=10.0, sigma=2.0))
                self.custom_logger.info(
                    "Applied multiplicative masks (mean-stdev, over_cached_scores): "
                    "r1=(loc=8.0, sigma=1.5, ±3σ), r2=(loc=10.0, sigma=2.0, ±3σ); δ_mech≤2⁻¹³."
                )
            mask_vec = [r1, 0, r1, 0, 0, -r2, 0, r2, 0] + [0] * (self.cc_batch_size - 9)
            plaintext_mask = self._cct.MakeCKKSPackedPlaintext(mask_vec, level=level_val)
            local_list_enc_result = self.op_two_cipher_list("mult", ctx, plaintext_mask)

            local_list_enc_result = self.op_compress_cipherlist(local_list_enc_result, 2, 1)

            list_ciphers = serialize_cipherlist(local_list_enc_result)

        elif computation_type == "chi2":
            # 1. Sum/Multiply (in a recursive way).
            keys = ["cont_table", "row_marg", "col_marg", "zeros_row", "zeros_col", "N_sum"]
            dict_list_ciphers = {}
            for key in keys:
                client_lists = [deserialize_cipherlist(client_share["ciphertext"][key]) for client_share in accepted_data.values()]
                if local_analysed_data is not None: # Include own data if available
                    client_lists.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[key], level = level_val))  # TODO: Support cohorts larger than the CKKS batch size by packing into a list of plaintexts.

                if key in ["cont_table", "row_marg", "col_marg", "N_sum"]:
                    dict_list_ciphers[key] = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)
                elif key in ["zeros_row", "zeros_col"]:
                    dict_list_ciphers[key] = log_tree_op("mult", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)
                else:
                    raise ValueError(f"Unsupported cipher for chi2 computation: {key}")

            # 2. Compute the expected values
            expected_values = self.op_two_cipher_list("mult", dict_list_ciphers["row_marg"], dict_list_ciphers["col_marg"])

            # 3. Compute the observed values
            observed_values = self.op_two_cipher_list("mult", dict_list_ciphers["cont_table"], dict_list_ciphers["N_sum"])

            # 4. Compute the numerator and denominator for chi2 statistic
            numerator = self.op_two_cipher_list("sub", observed_values, expected_values)
            numerator = self.op_two_cipher_list("mult", numerator, numerator)
            denominator = self.op_two_cipher_list("mult", expected_values, dict_list_ciphers["N_sum"])

            # 5. Flag the cells whose expected value is zero, so the masking below can give them a
            # dummy denominator instead of dividing by zero.
            zeroes_table = self.zero_expected_value_mask(dict_list_ciphers["zeros_row"], dict_list_ciphers["zeros_col"])

            # 6. Compute the number of zero values
            num_zeroes_rows = None
            num_zeroes_cols = None
            dict_list_ciphers["zeros_row"] = self.op_two_cipher_list("evalsum", dict_list_ciphers["zeros_row"], self.cc_batch_size)
            dict_list_ciphers["zeros_col"] = self.op_two_cipher_list("evalsum", dict_list_ciphers["zeros_col"], self.cc_batch_size)
            for cipher in dict_list_ciphers["zeros_row"]:
                if num_zeroes_rows is None:
                    num_zeroes_rows = cipher
                else:
                    self._cct.EvalAddInPlace(num_zeroes_rows, cipher)
            for cipher in dict_list_ciphers["zeros_col"]:
                if num_zeroes_cols is None:
                    num_zeroes_cols = cipher
                else:
                    self._cct.EvalAddInPlace(num_zeroes_cols, cipher)

            # 7. Compute the degrees of freedom over the categories that survive, i.e.
            # (rows - 1 - empty_rows) * (cols - 1 - empty_cols).
            # ``zeros_row``/``zeros_col`` were broadcast over the flattened table (each row flag
            # repeated len_category_2 times, each column flag tiled len_category_1 times), so the
            # EvalSum totals above are len_category_2*empty_rows and len_category_1*empty_cols.
            # Scale the constants by the same factors instead of rescaling the ciphertexts -- a
            # plaintext EvalMult would cost a multiplicative level, a scalar EvalSub costs none --
            # and divide the len_category_1*len_category_2 back out after decryption.
            len_category_1 = metadata["len_category1"]
            len_category_2 = metadata["len_category2"]
            self._cct.EvalSubInPlace((len_category_1 - 1) * len_category_2, num_zeroes_rows)
            self._cct.EvalSubInPlace((len_category_2 - 1) * len_category_1, num_zeroes_cols)
            dof = [self._cct.EvalMult(num_zeroes_rows, num_zeroes_cols)]

            # Random masking (increases depth requirement from 4 to 7)
            # 1. Sample a vector of random values as in Multiplicative Masking

            num_values = len_category_1 * len_category_2
            num_ciphers = math.ceil(num_values / self.cc_batch_size)

            # Multiplicative mask
            r = []
            r_scaled = []
            for i in range(num_ciphers):
                cipher_mask = []
                for j in range(self.cc_batch_size):
                    cipher_mask.append(abs(multiplicative_mask(loc=9.5, sigma=3.17)))
                # r.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask))
                # r_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**4) for x in cipher_mask]))
                r_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**3) for x in cipher_mask], level = level_val))
            self.custom_logger.info(f"Applied multiplicative mask: loc = 9.5, sigma=3.17.")

            # Additive shares of zero. lambda_val sets the mask magnitude and trades masking
            # strength against CKKS precision: the shares are recovered by dividing the decrypted
            # numerator2 by denominator1, so their leftover after cancellation scales with lambda.
            # The 2**20 default costs ~20 bits of precision (statistic good to only ~2 decimals);
            # 2**15 buys ~5 of them back (clears the second-decimal drift) while keeping the
            # per-cell leak probability at ~1 in 32768 (2**-15) -- well above 2**10's 1 in 1024.
            lambda_val = 2**15
            ra_prime = []
            additive_mask_values = additive_mask(num_values, lambda_val=lambda_val)
            for i in range(num_ciphers):
                cipher_mask_values = additive_mask_values[i * self.cc_batch_size:(i + 1) * self.cc_batch_size]
                ra_prime.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask_values, level = level_val))
            self.custom_logger.info(f"Applied additive mask: (lambda_val=2**15).")

            # 2. Compute denominator1 = denominator * (1 - zeros_table) * r + zeros_table * r
            temp_one_minus_zeros_table = self.op_two_cipher_list("sub", 1, zeroes_table)
            denominator1 = self.op_two_cipher_list("mult", denominator, temp_one_minus_zeros_table)
            denominator1 = self.op_two_cipher_list("add", denominator1, zeroes_table)
            denominator1 = self.op_two_cipher_list("mult", denominator1, r_scaled)

            # 3. Compute numerator1 = numerator * (1 - zeros_table) * r
            numerator1 = self.op_two_cipher_list("mult", numerator, temp_one_minus_zeros_table)
            numerator1 = self.op_two_cipher_list("mult", numerator1, r_scaled)

            # 4. Compute mask = ra_prime * denominator1
            mask = self.op_two_cipher_list("mult", ra_prime, denominator1)

            # 5. Compute the new numerator2 by summing numerator1 and the mask.
            numerator2 = self.op_two_cipher_list("add", numerator1, mask)

            local_list_enc_result = {
                "numerator": numerator2,
                "denominator": denominator1,
                "dof": dof
            }

            local_list_enc_result["numerator"] = self.op_compress_cipherlist(local_list_enc_result["numerator"], 2, 1)  # Higher susceptibility to decryption failure
            local_list_enc_result["denominator"] = self.op_compress_cipherlist(local_list_enc_result["denominator"], 2, 2)  # Higher susceptibility to decryption failure
            local_list_enc_result["dof"] = self.op_compress_cipherlist(local_list_enc_result["dof"], 1, 1)

            # Serialize all ciphertexts for the payload
            payload_ciphers = {}
            for key, value in local_list_enc_result.items():
                if isinstance(value, dict): # Nested dictionaries for groups
                    payload_ciphers[key] = {}
                    for sub_key, sub_value in value.items():
                        payload_ciphers[key][sub_key] = serialize_cipherlist(sub_value)
                elif isinstance(value, list): # Flat lists of ciphers
                    payload_ciphers[key] = serialize_cipherlist(value)
                else:
                    raise ValueError(f"Unexpected type in local_list_enc_result for serialization: {type(value)}")

            return {"enc_result": payload_ciphers}, local_list_enc_result

        elif computation_type in ENC_BIOMARKER_DOT_PRODUCT_TYPES:
            # The model is uploaded pre-encrypted by the leader during
            # workflow_model_upload; the server loads the ciphertexts + the rsf the
            # persistor resolved and never sees the plaintext coefficients/cutoff.
            #
            # SKIP_CUTOFF: the split producer biomarker_enc_score_cache packs the rsf-scaled
            # score with NO cutoff subtraction (and no rm/descale) and caches it for the KM/LCS
            # postprocess consumers to threshold/descale later. Discovery
            # (biomarker_enc_risk_group_computation) subtracts the baked cutoff here. Neither
            # branch uses plaintext rsf.
            SKIP_CUTOFF = computation_type in ENC_BIOMARKER_SKIP_CUTOFF_TYPES
            IS_MODEL_ENCRYPTED = True

            model_keys = list(metadata["model_keys"])
            biomarker_models_by_key = metadata["biomarker_models_by_key"]

            cov_length = len(metadata["covs"])
            cov_length = 2 **(math.ceil(math.log2(cov_length))) # Round cov_length to next power of 2

            patients_per_batch = self.cc_batch_size // cov_length
            if patients_per_batch < 1:
                raise ValueError("Error: Our assumption that batch_size >= cov_length is violated.")

            ser_models = []
            risk_scores_scale_factor_by_model = {}
            for mk in model_keys:
                paths = biomarker_models_by_key[mk]
                with open(paths["coeff_ct_file_path"], "rb") as f:
                    ser_coeff = f.read()
                with open(paths["cutoff_ct_file_path"], "rb") as f:
                    ser_cutoff = f.read()
                ser_models.append((ser_coeff, ser_cutoff))
                if not SKIP_CUTOFF:
                    # Discovery threads the plaintext rsf into metadata (KM dead-band).
                    # Scoring descales homomorphically via the encrypted 1/rsf and never
                    # reads plaintext rsf -- by_key carries no "rsf" for the scoring path.
                    risk_scores_scale_factor_by_model[mk] = float(paths["rsf"])

            if risk_scores_scale_factor_by_model:
                metadata["risk_scores_scale_factor_by_model"] = risk_scores_scale_factor_by_model

            mask_pattern = [1] + [0] * (cov_length - 1)
            mask_full = []
            for _ in range(patients_per_batch):
                mask_full.extend(mask_pattern)
            if len(mask_full) < self.cc_batch_size:
                mask_full.extend([0] * (self.cc_batch_size - len(mask_full)))

            # Add Gaussian noise for securing the model parameters.
            num_clients = len(accepted_data)
            sigma_val, B_val = self._biomarker_model_mask_params(num_clients)
            # Discovery hides the score magnitude with a per-slot multiplicative mask ``rm``
            # (max=e**(B/num_clients), min=e**(-B/num_clients)) that preserves the sign of
            # ``score - cutoff``. The LCS scoring path (SKIP_CUTOFF) keeps the magnitude and never uses
            # ``rm``, so skip building it entirely. Vectorized: one normal draw + clip + exp over all
            # slots (was cc_batch_size scalar np.random.normal calls). It's a random mask, so any valid
            # draw is correct.
            rm = None
            if not SKIP_CUTOFF:
                scale_val = sigma_val / math.sqrt(num_clients)
                bound = B_val / num_clients
                z = np.random.normal(0.0, scale_val, size=self.cc_batch_size)
                rm = np.exp(np.clip(z, -bound, bound))

            # Score the SERVER's own patients too, when the server is a data owner. Its plaintext
            # covariates (local_analysed_data, from analytics_manager.preprocess()) are encrypted
            # HERE under the multiparty public key with the exact same packing as the clients
            # (exec_encrypt_stat_analytics) and added as an extra "site" keyed by
            # biomarker_server_risk_key. The model stays hidden from the server (it only ever
            # holds ciphertext); the server's scores are recovered later via the standard
            # multiparty decryption (the server is the legitimate owner of this slice, so no
            # hide-from-lead random mask is applied to it -- see _decrypt_stat_analytics_single_shares).
            # NOTE: num_clients above (and thus the model-hiding Gaussian mask calibration) is
            # intentionally the CLIENT count only; the server slice is scored with the same mask.
            scoring_data = dict(accepted_data)
            if local_analysed_data is not None:
                server_enc = self.exec_encrypt_stat_analytics(0, computation_type, local_analysed_data, depth_required)
                if server_enc.get("ciphertext"):
                    scoring_data[biomarker_server_risk_key] = {"ciphertext": server_enc["ciphertext"]}

            # Prepare shifted masks for each cipher in order to align slots across batches.
            #
            # Each patient cipher's scores are packed into ONE slot per patient of an output
            # cipher: patient cipher ``c`` writes to offset ``c % cov_length`` inside every
            # cov_length-wide patient block. There are only cov_length distinct offsets and
            # patients_per_batch blocks, so a single output cipher saturates at
            # ``cov_length * patients_per_batch == cc_batch_size`` patients -- one per slot,
            # which is already optimal packing. Cohorts larger than that therefore need
            # SEVERAL output ciphers: patient cipher ``c`` contributes to output cipher
            # ``c // cov_length``. This used to raise ValueError once a client held
            # cov_length patient ciphers, which capped a cohort at cc_batch_size patients.
            max_num_batches = max(len(client_data.get("ciphertext")) for client_data in scoring_data.values())
            num_out_ciphers = max(1, math.ceil(max_num_batches / cov_length))
            if num_out_ciphers > 1:
                self.custom_logger.info(
                    "biomarker packing: max_num_batches=%s exceeds cov_length=%s -> %s output "
                    "ciphers per (model, client); cohort capacity is %s patients per output cipher.",
                    max_num_batches, cov_length, num_out_ciphers, self.cc_batch_size,
                )
            shift_mask_data_list = []
            for idx_patient in range(max_num_batches):
                offset = idx_patient % cov_length
                shift_mask = [0] * offset + [1] + [0] * (cov_length - offset - 1)
                shift_mask_full = shift_mask * patients_per_batch
                if len(shift_mask_full) < self.cc_batch_size:
                    shift_mask_full.extend([0] * (self.cc_batch_size - len(shift_mask_full)))
                if SKIP_CUTOFF:
                    # Scoring flow: discovery folds the multiplicative mask ``rm`` in to
                    # hide the magnitude while preserving the sign of ``score - cutoff``.
                    # Scoring needs the magnitude, and ``rm`` has no client-side inverse,
                    # so keep only the structural shift_mask and drop ``rm``.
                    rm_mask_plus_filter_mask = shift_mask_full
                else:
                    # Combine the shift mask with the multiplicative mask (saves one EvalMult). rm is a
                    # NumPy array on this path; multiply vectorized and hand back a plain float list.
                    rm_mask_plus_filter_mask = (np.asarray(shift_mask_full, dtype=float) * rm).tolist()
                shift_mask_data_list.append(rm_mask_plus_filter_mask)


            # --------------------------- Parallel execution version ---------------------------
            # Prepare the heavy objects once for parallel processing
            ser_cc = self.serialize_cc()
            ser_multkey = Serialize(self._cct.GetEvalMultKeyVector(self.mp_public_key.GetKeyTag())[0], BINARY)
            ser_indexkeys = Serialize(self._cct.GetEvalAutomorphismKeyMap(self.mp_public_key.GetKeyTag()), BINARY)

            shm_cc = create_shm(ser_cc)
            shm_multkey = create_shm(ser_multkey)
            shm_indexkeys = create_shm(ser_indexkeys)
            shm_names = {"cc": shm_cc.name, "multkey": shm_multkey.name, "indexkeys": shm_indexkeys.name}
            sizes = {"cc": len(ser_cc), "multkey": len(ser_multkey), "indexkeys": len(ser_indexkeys)}

            CHUNK_SIZE = 4
            MAX_WORKERS = resolve_biomarker_max_workers(self.custom_logger)

            # --- parallel-performance instrumentation ---
            log_cov = int(math.log2(cov_length))
            self.custom_logger.info(
                "biomarker parallel setup: computation_type=%s cov_length=%s log_cov=%s "
                "patients_per_batch=%s CHUNK_SIZE=%s MAX_WORKERS=%s num_models=%s num_parties=%s | "
                "serialized bytes: cc=%s multkey=%s indexkeys=%s",
                computation_type, cov_length, log_cov, patients_per_batch, CHUNK_SIZE,
                MAX_WORKERS, len(model_keys), len(scoring_data),
                len(ser_cc), len(ser_multkey), len(ser_indexkeys),
            )
            _t_section_start = time.perf_counter()
            _t_merge_total = 0.0
            _num_chunks = 0
            _num_batches_total = 0
            _workers_spawned = 0

            # Force new spawned workers to use exactly 1 thread each.
            # This is critical to avoid oversubscription and potential deadlocks when using multiprocessing with OpenMP.
            # Each worker will read this environment variable when it starts and configure itself accordingly. The main process can still use multiple threads if needed, but the workers will be limited to 1 thread each.
            old_omp_threads = os.environ.get("OMP_NUM_THREADS")
            os.environ["OMP_NUM_THREADS"] = "1"

            # Per (model, client): a LIST of output ciphers, one per cc_batch_size patients.
            # Built as {out_idx: cipher} while chunks land out of order, then densified below.
            local_list_enc_result = {mk: {cn: {} for cn in scoring_data.keys()} for mk in model_keys}
            futures_map = {}
            try:
                ctx = multiprocessing.get_context("spawn")
                with concurrent.futures.ProcessPoolExecutor(
                    max_workers=MAX_WORKERS,
                    mp_context=ctx,
                    initializer=worker_init_biomarker,
                    initargs=(shm_names, sizes, level_val),
                ) as parallel_executor:
                    for client_name, client_data in scoring_data.items():
                        ser_patient_list = client_data.get("ciphertext") or []
                        num_batches = len(ser_patient_list)
                        if num_batches == 0:
                            continue
                        effective_chunk = min(CHUNK_SIZE, num_batches)
                        if effective_chunk < CHUNK_SIZE:
                            self.custom_logger.warning(
                                "Adjusted chunk size to %s for client %s with %s batches.",
                                effective_chunk,
                                client_name,
                                num_batches,
                            )
                        for i in range(0, num_batches, effective_chunk):
                            chunk_masks = shift_mask_data_list[i : i + effective_chunk]
                            chunk_ser_patients = [
                                cp if isinstance(cp, (bytes, str)) else Serialize(cp, BINARY)
                                for cp in ser_patient_list[i : i + effective_chunk]
                            ]
                            # Which output cipher each patient cipher in this chunk feeds.
                            chunk_out_idx = [
                                idx // cov_length
                                for idx in range(i, i + len(chunk_ser_patients))
                            ]
                            future = parallel_executor.submit(
                                _func_risk_score_multi_model_batch,
                                model_keys,
                                ser_models,
                                chunk_ser_patients,
                                mask_full,
                                chunk_masks,
                                cov_length,
                                level_val,
                                IS_MODEL_ENCRYPTED,
                                SKIP_CUTOFF,
                                chunk_out_idx,
                            )
                            futures_map[future] = client_name
                            _num_chunks += 1
                            _num_batches_total += len(chunk_ser_patients)

                    for future in concurrent.futures.as_completed(futures_map):
                        client_name = futures_map[future]
                        chunk_by_mk, (_fhe_pid, _fhe_worker, _fhe_iv) = future.result()
                        # "pool." because these workers ran concurrently: the seconds
                        # are CPU time, not elapsed time, and must not be added to this
                        # process's own serial total. Grouping by worker pid lets the
                        # report give the critical path (max worker) as well as the sum.
                        fhe_timing.merge(_fhe_worker, prefix="pool.", group=_fhe_pid,
                                         intervals=_fhe_iv)
                        # Serial main-thread merge (deserialize + EvalAdd of chunk results). Timed
                        # separately because it does NOT shrink with the per-worker rotation cut, so
                        # its share of wall time rises as worker compute drops (Amdahl).
                        _m0 = time.perf_counter()
                        for mk, by_out_idx in chunk_by_mk.items():
                            slot = local_list_enc_result[mk][client_name]
                            for oc, ser_ct in by_out_idx.items():
                                result_cipher = DeserializeCiphertextString(ser_ct, BINARY)
                                if oc not in slot:
                                    slot[oc] = result_cipher
                                else:
                                    self._cct.EvalAddInPlace(slot[oc], result_cipher)
                        _t_merge_total += time.perf_counter() - _m0
                    try:
                        _workers_spawned = len(parallel_executor._processes) or min(MAX_WORKERS, _num_chunks)
                    except Exception:
                        _workers_spawned = min(MAX_WORKERS, _num_chunks)
            finally:
                if old_omp_threads:
                    os.environ["OMP_NUM_THREADS"] = old_omp_threads
                else:
                    del os.environ["OMP_NUM_THREADS"]

            shm_cc.close()
            shm_cc.unlink()
            shm_multkey.close()
            shm_multkey.unlink()
            shm_indexkeys.close()
            shm_indexkeys.unlink()

            _t_section = time.perf_counter() - _t_section_start
            # Homomorphic-op profile per inner (model x patient-batch) iteration of the current
            # dot-product, by worker step (data-independent, so exact -- mirrors the loop in
            # _func_risk_score_multi_model_batch):
            #   ct*ct EvalMult  x1   (coef.x; relinearized -- the single most expensive op)
            #   reduce          : log_cov EvalRotate + log_cov EvalAdd
            #   ct*pt EvalMult  x1   (mask)
            #   shift EvalRotate x1
            #   broadcast       : log_cov EvalRotate + log_cov EvalAdd
            #   ct*pt EvalSub   x1   (cutoff; skipped on the score-only path when SKIP_CUTOFF)
            #   ct*pt EvalMult  x1   (shift-mask)
            #   EvalAdd x1           (accumulate; every batch after the first per model/client)
            _inner_iters = _num_batches_total * len(model_keys)
            _rot_per_inner = 2 * log_cov + 1
            _ctct_per_inner = 1                       # ct x ct mult (relinearization) -- dominates
            _ptmul_per_inner = 2                      # mask + shift-mask (ct x pt)
            _sub_per_inner = 0 if SKIP_CUTOFF else 1  # cutoff subtraction (ct x pt)
            self.custom_logger.info(
                "biomarker parallel done: workers_used=%s (cap=%s) chunks=%s batches=%s inner_iters=%s section_wall=%.3fs "
                "serial_merge_wall=%.3fs (%.1f%% of section) | per-inner ops: ctxct_mult=%s "
                "rotate=%s (reduce %s + shift 1 + broadcast %s) ptxt_mult=%s sub=%s "
                "[ct*ct relinearization dominates] | totals: ctxct_mult=%s rotate=%s",
                _workers_spawned, MAX_WORKERS, _num_chunks, _num_batches_total, _inner_iters, _t_section, _t_merge_total,
                (100.0 * _t_merge_total / _t_section) if _t_section > 0 else 0.0,
                _ctct_per_inner, _rot_per_inner, log_cov, log_cov, _ptmul_per_inner, _sub_per_inner,
                _inner_iters * _ctct_per_inner, _inner_iters * _rot_per_inner,
            )
            self.last_parallel_stats = {
                "fhe": fhe_timing.summary(),
                "workers_used": _workers_spawned,
                "workers_cap": MAX_WORKERS,
                "chunks": _num_chunks,
                "section_wall_sec": round(_t_section, 3),
            }

            # Densify {out_idx: cipher} -> ordered list, so slot k of the list is the k-th
            # cc_batch_size-wide window of the client's cohort. A client that contributed no
            # patients keeps an empty list (the [] sentinel the executor treats as "empty cohort").
            for mk, per_client in local_list_enc_result.items():
                for cn, by_out_idx in per_client.items():
                    per_client[cn] = [by_out_idx[oc] for oc in sorted(by_out_idx)]

            payload_ciphers = {}
            for mk, per_client in local_list_enc_result.items():
                payload_ciphers[mk] = {
                    cn: serialize_cipherlist(cts) for cn, cts in per_client.items() if cts
                }
            return {"enc_result": payload_ciphers}, local_list_enc_result

        elif computation_type == "kaplan-meier":

            all_group_names = set()
            for client_share in accepted_data.values():
                if "ciphertext" in client_share:
                    for group_name in client_share["ciphertext"].keys():
                        all_group_names.add(group_name)
            if local_analysed_data is not None: # Also include the server dataset
                all_group_names.update(local_analysed_data.keys())
            all_group_names = sorted(all_group_names)

            ci_type = metadata.get("CI_type", None)
            if ci_type is not None:
                local_list_enc_result = {"numerator_groups": {}, "denominator_groups": {}}
                for group_name in all_group_names:
                    N_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["N"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]
                    d_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["d"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]
                    if local_analysed_data is not None:
                        N_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["N"], level=level_val))
                        d_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["d"], level=level_val))
                    co_N_group = log_tree_op("add", N_ciphers_for_group, is_encrypted=True, op_fn=self.op_two_cipher_list)
                    co_d_group = log_tree_op("add", d_ciphers_for_group, is_encrypted=True, op_fn=self.op_two_cipher_list)
                    local_list_enc_result["numerator_groups"][group_name] = co_N_group
                    local_list_enc_result["denominator_groups"][group_name] = co_d_group
                payload_ciphers = {}
                for key, value in local_list_enc_result.items():
                    payload_ciphers[key] = {sub_key: serialize_cipherlist(sub_value) for sub_key, sub_value in value.items()}
                # Compress
                return {"enc_result": payload_ciphers}, local_list_enc_result

            if 'scale_factor' in metadata and metadata['scale_factor'] == 0:
                raise ValueError("scale_factor cannot be zero.")

            aggregated_group_ciphers = {}
            for group_name in all_group_names:
                N_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["N"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]
                d_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["d"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]
                zeros_N_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["zeros_N"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]
                ones_N_ciphers_for_group = [deserialize_cipherlist(client_share["ciphertext"][group_name]["ones_N"]) for client_share in accepted_data.values() if group_name in client_share["ciphertext"]]

                # TODO: Support cohorts larger than the CKKS batch size by packing into a list of plaintexts.
                # Include own data if available
                if local_analysed_data is not None:
                    N_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["N"], level = level_val))
                    d_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["d"], level = level_val))
                    zeros_N_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["zeros_N"], level = level_val))
                    ones_N_ciphers_for_group.append(self._cct.MakeCKKSPackedPlaintext(local_analysed_data[group_name]["ones_N"], level = level_val))

                co_N_group = log_tree_op("add", N_ciphers_for_group, is_encrypted=True, op_fn=self.op_two_cipher_list)
                co_d_group = log_tree_op("add", d_ciphers_for_group, is_encrypted=True, op_fn=self.op_two_cipher_list)
                co_zeros_N_group = log_tree_op("mult", zeros_N_ciphers_for_group, is_encrypted=True, op_fn=self.op_two_cipher_list)

                # Compute co_ones_N_group by summing mutually exclusive cases
                terms_for_ones = []
                num_shares = len(zeros_N_ciphers_for_group)
                for i in range(num_shares):
                    factors = []
                    for j in range(num_shares):
                        if i == j:  # Use the "One" indicator for the current client
                            factors.append(ones_N_ciphers_for_group[j])
                        else:   # Use the "Zero" indicator for all other clients
                            factors.append(zeros_N_ciphers_for_group[j])
                    # Multiply factors to check this specific case (Client i is the only one with data)
                    term_i = log_tree_op("mult", factors, is_encrypted=True, op_fn=self.op_two_cipher_list)
                    terms_for_ones.append(term_i)
                if terms_for_ones:  # Sum up all the mutually exclusive cases
                    co_ones_N_group = log_tree_op("add", terms_for_ones, is_encrypted=True, op_fn=self.op_two_cipher_list)
                else:   # Fallback if no data exists (unlikely in valid flow)
                    co_ones_N_group = zeros_N_ciphers_for_group[0]

                aggregated_group_ciphers[group_name] = {
                    "N": co_N_group,
                    "d": co_d_group,
                    "zeros_N": co_zeros_N_group,
                    "ones_N": co_ones_N_group,
                }

            # Prepare initial output structure for decryption
            local_list_enc_result = {}

            if len(all_group_names) == 2:
                group_A_name, group_B_name = all_group_names[0], all_group_names[1]

                co_N_group_A = aggregated_group_ciphers[group_A_name]["N"]
                co_d_group_A = aggregated_group_ciphers[group_A_name]["d"]
                co_zeros_N_A = aggregated_group_ciphers[group_A_name]["zeros_N"]
                co_ones_N_A = aggregated_group_ciphers[group_A_name]["ones_N"]

                co_N_group_B = aggregated_group_ciphers[group_B_name]["N"]
                co_d_group_B = aggregated_group_ciphers[group_B_name]["d"]
                co_zeros_N_B = aggregated_group_ciphers[group_B_name]["zeros_N"]
                co_ones_N_B = aggregated_group_ciphers[group_B_name]["ones_N"]

                # Sum across all groups
                co_N = self.op_two_cipher_list("add", co_N_group_A, co_N_group_B)
                co_d = self.op_two_cipher_list("add", co_d_group_A, co_d_group_B)

                # Multiply zeros_N_group, ones_N_group across all groups
                co_zeros_N = self.op_two_cipher_list("mult", co_zeros_N_A, co_zeros_N_B)
                case_A1_B0 = self.op_two_cipher_list("mult", co_ones_N_A, co_zeros_N_B)
                case_A0_B1 = self.op_two_cipher_list("mult", co_zeros_N_A, co_ones_N_B)
                co_ones_N = self.op_two_cipher_list("add", case_A1_B0, case_A0_B1)
                # co_ones_N = self.op_two_cipher_list("mult", co_ones_N_A, co_ones_N_B)

                # Compute co_zeros_ones_N = co_zeros_N + co_ones_N (simulates OR for 0/1 indicators)
                co_zeros_ones_N = self.op_two_cipher_list("add", co_zeros_N, co_ones_N)

                # Compute the numerator of the expected value associated to group A
                # numerator_A = co_N * co_d_group_A - co_d * co_N_group_A
                temp1 = self.op_two_cipher_list("mult", co_N, co_d_group_A)
                temp2 = self.op_two_cipher_list("mult", co_d, co_N_group_A)
                numerator_A = self.op_two_cipher_list("sub", temp1, temp2)

                # Set the denominator of the expected value associated to group A
                denominator_A = co_N

                # Compute the numerator of the variance in group A
                # numerator_var_A = co_N_group_A * (co_N - co_N_group_A) * co_d * (co_N - co_d)
                term1_var = self.op_two_cipher_list("mult", co_N_group_A, self.op_two_cipher_list("sub", co_N, co_N_group_A))
                term2_var = self.op_two_cipher_list("mult", co_d, self.op_two_cipher_list("sub", co_N, co_d))
                numerator_var_A = self.op_two_cipher_list("mult", term1_var, term2_var)

                # Compute the denominator of the variance in group A
                # denominator_var_A = co_N * co_N * (co_N - 1)
                term1_den_var = self.op_two_cipher_list("mult", co_N, co_N)
                term2_den_var = self.op_two_cipher_list("sub", co_N, 1)
                denominator_var_A = self.op_two_cipher_list("mult", term1_den_var, term2_den_var)


            # Random masking
            r = []
            r_scaled = []
            if self.ckks_data_type == "REAL":
                loc_val = 5.5
                sigma_val = 1.83
            else:
                loc_val = 14.5
                sigma_val = 3.89
            # The time grid is spread over ceil(len_time_grid / cc_batch_size) ciphers; cipher i
            # covers grid indices [i*batch, min((i+1)*batch, len_time_grid)). Each cipher gets a
            # mask sized to ITS OWN occupied slots -- using len_time_grid for every cipher
            # overflows the batch (MakeCKKSPackedPlaintext rejects >batch values) as soon as the
            # grid needs more than one cipher.
            # An empty grid yields no chunks (hence no mask ciphers), as before.
            _len_tg = metadata['len_time_grid']
            _grid_chunks = [
                (s, min(s + self.cc_batch_size, _len_tg))
                for s in range(0, _len_tg, self.cc_batch_size)
            ]
            for (c_start, c_end) in _grid_chunks:
                cipher_mask = [
                    multiplicative_mask(loc_val, sigma_val) for _ in range(c_end - c_start)
                ]
                r.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask, level = level_val))
                r_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / metadata["scale_factor"] for x in cipher_mask], level = level_val))
            self.custom_logger.info(f"Applied multiplicative mask: loc = {loc_val}, sigma={sigma_val}.")

            local_list_enc_result["numerator_groups"] = {}
            local_list_enc_result["denominator_groups"] = {}
            for group_name in all_group_names:
                co_N_group = aggregated_group_ciphers[group_name]["N"]
                co_d_group = aggregated_group_ciphers[group_name]["d"]
                numerator_group = self.op_two_cipher_list("sub", co_N_group, co_d_group)
                numerator_group = self.op_two_cipher_list("mult", numerator_group, r_scaled)
                denominator_group = self.op_two_cipher_list("mult", co_N_group, r_scaled)

                local_list_enc_result["numerator_groups"][group_name] = numerator_group
                local_list_enc_result["denominator_groups"][group_name] = denominator_group

            if len(all_group_names) == 2:
                # Same per-cipher chunking as the r/r_scaled masks above. The previous
                # ``len_time_grid % cc_batch_size`` was the size of the LAST (partial) cipher, so
                # full ciphers were under-filled and an exactly-divisible grid produced an empty
                # mask; combined with a stride of num_ciphers instead of cc_batch_size the chunks
                # also overlapped. Both were invisible while the grid fit in one cipher
                # (len_time_grid=97 << batch), which is the only case exercised so far.
                lambda_val = 2**10 #1048576.0
                self.custom_logger.info(f"Applied additive mask: (lambda_val=2**10).")
                rm_1 = []
                rm_2 = []
                rm_1_scaled = []
                rm_2_scaled = []
                ra_1 = []
                ra_2 = []
                ra_1_scaled = []
                ra_2_scaled = []

                rm = multiplicative_mask(loc_val, sigma_val)/ (metadata["scale_factor"]**1)
                for (c_start, c_end) in _grid_chunks:
                    cipher_mask1 = [
                        multiplicative_mask(loc_val, sigma_val) for _ in range(c_end - c_start)
                    ]
                    cipher_mask2 = [
                        multiplicative_mask(loc_val, sigma_val) for _ in range(c_end - c_start)
                    ]
                    rm_1.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask1, level = level_val))
                    rm_2.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask2, level = level_val))
                    rm_1_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**1) for x in cipher_mask1], level = level_val))
                    rm_2_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**2) for x in cipher_mask2], level = level_val))
                self.custom_logger.info(f"Applied multiplicative mask: loc = {loc_val}, sigma={sigma_val}.")

                # Shares of zero over the WHOLE grid; slicing by cipher keeps the total sum zero.
                additive_mask1 = additive_mask(metadata['len_time_grid'], lambda_val=lambda_val)
                additive_mask2 = additive_mask(metadata['len_time_grid'], lambda_val=lambda_val)
                for (c_start, c_end) in _grid_chunks:
                    cipher_mask1 = additive_mask1[c_start:c_end]
                    cipher_mask2 = additive_mask2[c_start:c_end]
                    ra_1.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask1, level = level_val))
                    ra_2.append(self._cct.MakeCKKSPackedPlaintext(cipher_mask2, level = level_val))
                    ra_1_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**1) for x in cipher_mask1], level = level_val))
                    ra_2_scaled.append(self._cct.MakeCKKSPackedPlaintext([x / (metadata["scale_factor"]**1) for x in cipher_mask2], level = level_val))

                # Apply masking for denominator_var_A
                # denominator_var_A = (denominator_var_A * (1 - co_zeros_ones_N) + co_zeros_ones_N) * rm_2.
                temp_one_minus_co_zeros_ones = self.op_two_cipher_list("sub", 1, co_zeros_ones_N)
                denominator_var_A = self.op_two_cipher_list("mult", denominator_var_A, temp_one_minus_co_zeros_ones)
                denominator_var_A = self.op_two_cipher_list("add", denominator_var_A, co_zeros_ones_N)
                denominator_var_A = self.op_two_cipher_list("mult", denominator_var_A, rm_2_scaled)

                # Apply masking for numerator_var_A
                # numerator_var_A = numerator_var_A * (1 - co_zeros_ones_N) * rm_2
                numerator_var_A = self.op_two_cipher_list("mult", numerator_var_A, temp_one_minus_co_zeros_ones)
                numerator_var_A = self.op_two_cipher_list("mult", numerator_var_A, rm_2_scaled)
                # numerator_var_A = rm * rm * (numerator_var_A + denominator_var_A * ra_2)
                term2_num_var_mask = self.op_two_cipher_list("mult", denominator_var_A, ra_2_scaled)
                numerator_var_A = self.op_two_cipher_list("add", numerator_var_A, term2_num_var_mask)
                numerator_var_A = self.op_two_cipher_list("mult", numerator_var_A, rm * rm)

                # # Apply masking for denominator_A
                # # denominator_A = denominator_A * rm_1.
                # denominator_A = self.op_two_cipher_list("mult", denominator_A, rm_1_scaled)

                # # Apply masking for numerator_A
                # # numerator_A = rm * (numerator_A * rm_1 + denominator_A * ra_1).
                # term1_num_A_mask = self.op_two_cipher_list("mult", numerator_A, rm_1_scaled)
                # term2_num_A_mask = self.op_two_cipher_list("mult", denominator_A, ra_1_scaled)
                # numerator_A = self.op_two_cipher_list("add", term1_num_A_mask, term2_num_A_mask)
                # numerator_A = self.op_two_cipher_list("mult", numerator_A, rm)

                '''Try2'''
                # # Apply masking for denominator_A
                # # denominator_A = (denominator_A * (1 - co_zeros_ones_N) + co_zeros_ones_N) * rm_1.
                # denominator_A = self.op_two_cipher_list("mult", denominator_A, temp_one_minus_co_zeros_ones)
                # denominator_A = self.op_two_cipher_list("add", denominator_A, co_zeros_ones_N)
                # denominator_A = self.op_two_cipher_list("mult", denominator_A, rm_1_scaled)

                # # Apply masking for numerator_A
                # # numerator_A = numerator_A * (1 - co_zeros_ones_N) * rm_1
                # numerator_A = self.op_two_cipher_list("mult", numerator_A, temp_one_minus_co_zeros_ones)
                # numerator_A = self.op_two_cipher_list("mult", numerator_A, rm_1_scaled)
                # # numerator_A = rm * (numerator_A + denominator_A * ra_1)
                # term2_num_A_mask = self.op_two_cipher_list("mult", denominator_A, ra_1_scaled)
                # numerator_A = self.op_two_cipher_list("add", numerator_A, term2_num_A_mask)
                # numerator_A = self.op_two_cipher_list("mult", numerator_A, rm)

                '''Try3'''
                # 1. Safe Denominator: D_safe = D * (1 - mask) + mask
                # If mask is 1 (N=0 or 1), D_safe becomes 1. If mask is 0, D_safe is D.
                denominator_A = self.op_two_cipher_list("mult", denominator_A, temp_one_minus_co_zeros_ones)
                denominator_A = self.op_two_cipher_list("add", denominator_A, co_zeros_ones_N)

                # 2. Apply Multiplicative Mask: D_final = D_safe * rm1
                denominator_A = self.op_two_cipher_list("mult", denominator_A, rm_1_scaled)

                # Apply masking for numerator_A
                # numerator_A = rm * (numerator_A * rm_1 + denominator_A * ra_1).

                # 3. Zero out numerator if mask is active: N_safe = N * (1 - mask)
                # This ensures that if we forced the denominator to 1 (dummy), the numerator is forced to 0.
                numerator_A = self.op_two_cipher_list("mult", numerator_A, temp_one_minus_co_zeros_ones)

                # 4. Standard mask logic
                term1_num_A_mask = self.op_two_cipher_list("mult", numerator_A, rm_1_scaled)
                term2_num_A_mask = self.op_two_cipher_list("mult", denominator_A, ra_1_scaled)
                numerator_A = self.op_two_cipher_list("add", term1_num_A_mask, term2_num_A_mask)
                numerator_A = self.op_two_cipher_list("mult", numerator_A, rm)


                local_list_enc_result.update({
                    "numerator_A": numerator_A,
                    "denominator_A": denominator_A,
                    "numerator_var_A": numerator_var_A,
                    "denominator_var_A": denominator_var_A,
                })


            for group_name in all_group_names:
                local_list_enc_result["numerator_groups"][group_name] = self.op_compress_cipherlist(local_list_enc_result["numerator_groups"][group_name], 2, 1)
                local_list_enc_result["denominator_groups"][group_name] = self.op_compress_cipherlist(local_list_enc_result["denominator_groups"][group_name], 2, 1)
            if len(all_group_names) == 2:
                local_list_enc_result["numerator_A"] = self.op_compress_cipherlist(local_list_enc_result["numerator_A"], 3, 1) # Higher susceptibility to decryption failure
                local_list_enc_result["denominator_A"] = self.op_compress_cipherlist(local_list_enc_result["denominator_A"], 3, 1)
                local_list_enc_result["numerator_var_A"] = self.op_compress_cipherlist(local_list_enc_result["numerator_var_A"], 4, 2) # Higher susceptibility to decryption failure
                local_list_enc_result["denominator_var_A"] = self.op_compress_cipherlist(local_list_enc_result["denominator_var_A"], 3, 2) # Higher susceptibility to decryption failure

            # Serialize all ciphertexts for the payload
            payload_ciphers = {}
            for key, value in local_list_enc_result.items():
                if isinstance(value, dict): # Nested dictionaries for groups
                    payload_ciphers[key] = {}
                    for sub_key, sub_value in value.items():
                        payload_ciphers[key][sub_key] = serialize_cipherlist(sub_value)
                elif isinstance(value, list): # Flat lists of ciphers
                    payload_ciphers[key] = serialize_cipherlist(value)
                else:
                    raise ValueError(f"Unexpected type in local_list_enc_result for serialization: {type(value)}")

            return {"enc_result": payload_ciphers}, local_list_enc_result

        elif computation_type == "t-test":
            client_lists = [deserialize_cipherlist(client_share.get("ciphertext")) for client_share in accepted_data.values()]
            if local_analysed_data is not None: # Include own data if available
                categories = list(local_analysed_data.keys())
                categories.sort()
                client_lists.append(self._cct.MakeCKKSPackedPlaintext([
                    local_analysed_data[categories[0]]['sum_sq'],
                    local_analysed_data[categories[0]]['sum'],
                    local_analysed_data[categories[0]]['count'],
                    local_analysed_data[categories[0]]['sum'],
                    local_analysed_data[categories[0]]['count'],
                    0, 0, 0,
                    local_analysed_data[categories[1]]['sum_sq'],
                    local_analysed_data[categories[1]]['sum'],
                    local_analysed_data[categories[1]]['count'],
                    local_analysed_data[categories[1]]['sum'],
                    local_analysed_data[categories[1]]['count'],
                    0, 0, 0
                ]*(self.cc_batch_size//16), level = level_val))

            # 1. Sum (in a recursive way).
            ctx = log_tree_op("add", client_lists, is_encrypted=True, op_fn=self.op_two_cipher_list)

            ctx_sl2 = [self._cct.EvalAtIndex(ctx[0], 2)]
            ctx_sl10 = [self._cct.EvalAtIndex(ctx_sl2[0], 8)]
            ctx_sl11 = [self._cct.EvalAtIndex(ctx_sl10[0], 1)]

            # ctx_sl10_prime = self.op_two_cipher_list("sub", ctx_sl10, self._cct.MakeCKKSPackedPlaintext([1,0,0,0,0,0,0,0]*3 + [0] * (self.cc_batch_size - 24))) # Version 1
            ctx_sl10_prime = self.op_two_cipher_list("sub", ctx_sl10, self._cct.MakeCKKSPackedPlaintext([1/metadata["global_count"],0,0,0,0,0,0,0]*3 + [0] * (self.cc_batch_size - 24), level = level_val))   # Version 2 (more robust)
            den_den_d = [self._cct.EvalAtIndex(ctx_sl10_prime[0], 8)]

            ctx = self.op_two_cipher_list("mult", ctx, ctx_sl2)
            ctx_prime = [self._cct.EvalRotate(ctx[0], 1)]
            self._cct.EvalSubInPlace(ctx[0], ctx_prime[0])
            ctx = self.op_two_cipher_list("mult", ctx, ctx_sl10_prime)
            temp1 = self.op_two_cipher_list("mult", ctx_sl10, ctx_sl10)
            ctx = self.op_two_cipher_list("mult", ctx, temp1)
            num_den_d = ctx

            ctx_prime = [self._cct.EvalAtIndex(ctx[0], 8)]
            num_d = self.op_two_cipher_list("add", ctx, ctx_prime)

            den_t = num_d

            num_t = self.op_two_cipher_list("mult", ctx_sl2, ctx_sl11)
            ctx_prime = [self._cct.EvalAtIndex(num_t[0], 1)]
            self._cct.EvalSubInPlace(num_t[0], ctx_prime[0])
            # ctx = self.op_two_cipher_list("sub", ctx_sl2, self._cct.MakeCKKSPackedPlaintext([1] + [0]*(self.cc_batch_size - 1)))    # Version 1
            ctx = self.op_two_cipher_list("sub", ctx_sl2, self._cct.MakeCKKSPackedPlaintext([1/metadata["global_count"]] + [0]*(self.cc_batch_size - 1), level = level_val))  # Version 2 (more robust)
            temp1 = self.op_two_cipher_list("mult", num_t, ctx)
            num_t = self.op_two_cipher_list("mult", num_t, ctx_sl10_prime)
            num_t = self.op_two_cipher_list("mult", num_t, temp1)

            # Random Masking

            if self.ckks_data_type == "REAL":
                loc_val = 13
                sigma_val = 5
            else:
                loc_val = 19.52
                sigma_val = 5.22
            rm1 = abs(multiplicative_mask(loc_val, sigma_val))
            rm2 = [abs(multiplicative_mask(loc_val, sigma_val)), abs(multiplicative_mask(loc_val, sigma_val))]
            rm3 = abs(multiplicative_mask(loc_val, sigma_val))

            # '''Version 1
            # Scaling + Masking (Less aggressive scaling to avoid noise issues)
            # Scaling applied to reduce magintude of values for 1) avoiding overflow and 2) ensuring masks are applied over values with num/den within [-1,1].
            # - num_den_d**2/den_den_d has range up to [g_n0^3 * g_n1^6, g_n0^6 * g_n1^3].
            #     - num_den_d [0, 1] -> [num_den_d[0] / (g_n0 * g_n1^2), num_den_d[1] / (g_n0^2 * g_n1)]
            #     - den_den_d [0, 1] -> [den_den_d[0] * (g_n0 * g_n1^2), den_den_d[1] * (g_n0^2 * g_n1)]
            #     - Now, num_den_d has range g_n0*g_n1 and den_den_d has range (g_n0*g_n1)^2.
            #     - Thus, num_den_d**2/den_den_d has range up to 1, which ensures mask security.
            # - num_d has range up to g_n0^2 * g_n1^2 * (g_n0 + g_n1).
            #     - num_d**2/(num_den_d**2/den_den_d) has range up to g_n0 * g_n1 * (g_n0 + g_n1)**3/(g_n0**3 + g_n1**3).
            #     - To simplify, let's consider (g_n0*g_n1)^2. g_n0 * g_n1 * (g_n0 + g_n1)**3/(g_n0**3 + g_n1**3) <= (g_n0*g_n1)^2.
            #     - We will consider (g_n0*g_n1)^2 as the scaling factor for num_d^2.
            #     - For keeping the num_d values small, consider a larger scaling factor of (g_n0*g_n1)^2 for num_d.
            #     - So, we scale num_d by dividing by (g_n0*g_n1)^2 to ensure mask security.
            #     - Now, num_d has range up to g_n0*g_n1*(g_n0 + g_n1).
            # - num_t has range up to 4 * g_n0^3 * g_n1^3.
            #     - den_t has up to range(num_d) = g_n0^2 * g_n1^2 * (g_n0 + g_n1).
            #     - num_t/den_t has range up to 4 * g_n0 * g_n1 / (g_n0 + g_n1).
            #     - We consider dividing num_t by (g_n0*g_n1)^2 and dividing den_t by (g_n0*g_n1).
            #     - Now, num_t has range up to 4*g_n0*g_n1 and den_t has range up to g_n0*g_n1*(g_n0 + g_n1).
            #     - Thus, num_t/den_t has range up to 4/(g_n0 + g_n1), which ensures mask security as long as (g_n0 + g_n1) > 4 [Assumption].
            # '''
            # g_n0 = metadata["scale_factor"][categories[0]]  # Global count of category 0
            # g_n1 = metadata["scale_factor"][categories[1]]
            # rm_num_d = self._cct.MakeCKKSPackedPlaintext([math.sqrt(rm1)/((g_n0*g_n1)**2)] + [0]*(self.cc_batch_size - 1))
            # rm_num_den_d = self._cct.MakeCKKSPackedPlaintext([math.sqrt(rm1*rm2[0])/(g_n0 * g_n1**2),0,0,0,0,0,0,0, math.sqrt(rm1*rm2[1])/(g_n0**2 * g_n1),0,0,0,0,0,0,0] + [0]*(self.cc_batch_size - 16))
            # rm_den_den_d = self._cct.MakeCKKSPackedPlaintext([rm2[0]* (g_n0 * g_n1**2),0,0,0,0,0,0,0, rm2[1]* (g_n0**2 * g_n1),0,0,0,0,0,0,0] + [0]*(self.cc_batch_size - 16))
            # rm_num_t = self._cct.MakeCKKSPackedPlaintext([rm3/((g_n0*g_n1)**2)] + [0]*(self.cc_batch_size - 1))
            # rm_den_t = self._cct.MakeCKKSPackedPlaintext([rm3/(g_n0*g_n1)] + [0]*(self.cc_batch_size - 1))

            # Version 2 (more robust)
            rm_num_d = self._cct.MakeCKKSPackedPlaintext([math.sqrt(rm1)] + [0]*(self.cc_batch_size - 1), level = level_val)
            rm_num_den_d = self._cct.MakeCKKSPackedPlaintext([math.sqrt(rm1*rm2[0]),0,0,0,0,0,0,0, math.sqrt(rm1*rm2[1]),0,0,0,0,0,0,0] + [0]*(self.cc_batch_size - 16), level = level_val)
            rm_den_den_d = self._cct.MakeCKKSPackedPlaintext([rm2[0],0,0,0,0,0,0,0, rm2[1],0,0,0,0,0,0,0] + [0]*(self.cc_batch_size - 16), level = level_val)
            rm_num_t = self._cct.MakeCKKSPackedPlaintext([rm3] + [0]*(self.cc_batch_size - 1), level = level_val)
            rm_den_t = self._cct.MakeCKKSPackedPlaintext([rm3] + [0]*(self.cc_batch_size - 1), level = level_val)
            num_d = self.op_two_cipher_list("mult", num_d, rm_num_d)
            num_den_d = self.op_two_cipher_list("mult", num_den_d, rm_num_den_d)
            den_den_d = self.op_two_cipher_list("mult", den_den_d, rm_den_den_d)
            num_t = self.op_two_cipher_list("mult", num_t, rm_num_t)
            den_t = self.op_two_cipher_list("mult", den_t, rm_den_t)
            self.custom_logger.info(f"Applied multiplicative mask: loc = {loc_val}, sigma={sigma_val}.")

            local_list_enc_result = {
                "num_d": num_d,
                "num_den_d": num_den_d,
                "den_den_d": den_den_d,
                "num_t": num_t,
                "den_t": den_t
            }

            local_list_enc_result["num_d"] = self.op_compress_cipherlist(local_list_enc_result["num_d"], 3, 2)
            local_list_enc_result["num_den_d"] = self.op_compress_cipherlist(local_list_enc_result["num_den_d"], 3, 2)
            local_list_enc_result["den_den_d"] = self.op_compress_cipherlist(local_list_enc_result["den_den_d"], 3, 2)
            local_list_enc_result["num_t"] = self.op_compress_cipherlist(local_list_enc_result["num_t"], 3, 2)
            local_list_enc_result["den_t"] = self.op_compress_cipherlist(local_list_enc_result["den_t"], 4, 2)

            # Serialize all ciphertexts for the payload
            payload_ciphers = {}
            for key, value in local_list_enc_result.items():
                if isinstance(value, dict): # Nested dictionaries for groups
                    payload_ciphers[key] = {}
                    for sub_key, sub_value in value.items():
                        payload_ciphers[key][sub_key] = serialize_cipherlist(sub_value)
                elif isinstance(value, list): # Flat lists of ciphers
                    payload_ciphers[key] = serialize_cipherlist(value)
                else:
                    raise ValueError(f"Unexpected type in local_list_enc_result for serialization: {type(value)}")

            return {"enc_result": payload_ciphers}, local_list_enc_result

        else:
            raise ValueError(f"Unsupported computation type: {computation_type}")
        return {"enc_result": list_ciphers}, local_list_enc_result

    # ---------------------------------------------------------------------------------
    # Client-Side (Executor) Functions
    # ---------------------------------------------------------------------------------
    def exec_init_mix(self, dxo, client_name, workspace_root):
        '''Handles the client-side `task_init_mix`.

        This is used in the "mix" architecture where the server generates the
        CryptoContext. This function simply receives the CC from the server
        and saves it locally.
        '''
        self.cc = DeserializeCryptoContextString(dxo.data["CC"], BINARY)
        return {}

    def exec_keygen_star_round0(self, dxo, client_name, workspace_root):
        '''Handles the client-side Round 0 of Star-architecture key generation.

        1. Receives the server's CryptoContext and public key.
        2. Generates its own key pair (skC, pkC) for multi-party operations.
        3. Generates its shares of the evaluation keys.
        4. Saves its secret key (skC) locally.
        5. Returns its public key (pkC) and evaluation key shares to be sent to the server.
        '''
        # Receive the CryptoContext and initial keys from aggregator.
        self.cc = DeserializeCryptoContextString(dxo.data["CC"], BINARY)
        kp = self._cct.MultipartyKeyGen(DeserializePublicKeyString(dxo.data["pk"], BINARY), False, True)
        self.mult_depth = dxo.get_meta_prop("mult_depth")
        self.cc_batch_size = dxo.get_meta_prop("cc_batch_size")
        self.ckks_data_type = dxo.get_meta_prop("ckks_data_type")
        public_key_share = kp.publicKey
        self.secret_key = kp.secretKey
        self.custom_logger.info("Received server's PK. Generated own key pair (skC, pkC).")

        weights = {
            "public_key_share": Serialize(public_key_share, BINARY)
        }
        if "evalMultKey" in dxo.data:
            self.generate_mult_keys = True
            evalMultKey = DeserializeEvalKeyString(dxo.data["evalMultKey"], BINARY)
            evalMultKey2 = self._cct.MultiKeySwitchGen(kp.secretKey, kp.secretKey, evalMultKey)
            weights["evalMultKey2"] = Serialize(evalMultKey2, BINARY)
        if "evalSumKeys" in dxo.data:
            self.generate_sum_keys = True
            evalSumKeys = DeserializeEvalKeyMapString(dxo.data["evalSumKeys"], BINARY)
            evalSumKeysB = self._cct.MultiEvalSumKeyGen(kp.secretKey, evalSumKeys, kp.publicKey.GetKeyTag())
            weights["evalSumKeysB"] = Serialize(evalSumKeysB, BINARY)
        if "evalAtIndexKeys" in dxo.data:
            self.generate_index_keys = True
            if "indices" not in dxo.data:
                raise Exception(f"{client_name}: Indices not provided for evalAtIndexKeys")
            evalAtIndexKeys = DeserializeEvalKeyMapString(dxo.data["evalAtIndexKeys"], BINARY)
            indices = dxo.data["indices"]
            evalAtIndexKeysB = self._cct.MultiEvalAtIndexKeyGen(kp.secretKey, evalAtIndexKeys, indices, kp.publicKey.GetKeyTag())
            weights["evalAtIndexKeysB"] = Serialize(evalAtIndexKeysB, BINARY)

        self.custom_logger.info(f"Generated eval key shares (Mult: {self.generate_mult_keys}, Sum: {self.generate_sum_keys}, Index: {self.generate_index_keys}).")

        return weights

    def exec_keygen_star_round1(self, dxo, client_name, workspace_root):
        '''Handles the client-side Round 1 of Star-architecture key generation.

        1. Receives the aggregated multi-party public key (mpPK) and intermediate
           evaluation keys from the server.
        2. Generates its final share of the evaluation keys.
        3. Saves the mpPK and the final CryptoContext locally.
        4. Returns its final evaluation key share to be sent to the server.
        '''
        weights = {}
        # Receive multi-party public key and relin key from aggregator.
        self.mp_public_key = DeserializePublicKeyString(dxo.data["public_key"], BINARY)
        if "evalMultAB" in dxo.data:
            evalMultAB = DeserializeEvalKeyString(dxo.data["evalMultAB"], BINARY)
            evalMultBAB = self._cct.MultiMultEvalKey(self.secret_key, evalMultAB, self.mp_public_key.GetKeyTag())
            weights["evalMultBAB"] = Serialize(evalMultBAB, BINARY)

        self.custom_logger.info(f"Received aggregated multi-party public_key. Generated mult-key share = {self.generate_mult_keys}.")

        return weights

    def exec_keygen_cc_round0(self, client_name, workspace_root):
        '''Handles the client-side Round 0 of CC-architecture key generation (leader only).

        This function is executed only by the designated 'leader' client.
        1. Initializes the CryptoContext.
        2. Generates a standard (single-party) key pair and evaluation keys.
        3. Saves its secret key locally.
        4. Returns the CC, public key, and evaluation keys to be sent to the server.
        '''
        # if debug:
        #     print(f"\n--- [DEBUG] {client_name} (Leader): exec_keygen_cc_round0 ---")

        self.cc, res = DeserializeCryptoContext(workspace_root+"/cryptocontext.bin", BINARY)
        if not res:
            self.initialize_openfhe()

        # Generate keys
        kp = self._cct.KeyGen()
        self.secret_key = kp.secretKey
        weights = {
            "CC": Serialize(self.cc, BINARY),
            "public_key_share": Serialize(kp.publicKey, BINARY)
        }
        if self.generate_mult_keys:
            if self.is_MultiParty:
                evalMultKey = self._cct.KeySwitchGen(self.secret_key, self.secret_key)
            else:
                self._cct.EvalMultKeyGen(self.secret_key)
                evalMultKey = self._cct.GetEvalMultKeyVector(kp.secretKey.GetKeyTag())[0]
            weights["evalMultKey"] = Serialize(evalMultKey, BINARY)
        if self.generate_sum_keys:
            self._cct.EvalSumKeyGen(kp.secretKey)
            evalSumKeys = self._cct.GetEvalSumKeyMap(kp.secretKey.GetKeyTag())
            weights["evalSumKeys"] = Serialize(evalSumKeys, BINARY)
        if self.generate_index_keys:
            self._cct.EvalAtIndexKeyGen(kp.secretKey, self.indices)
            evalAtIndexKeys = self._cct.GetEvalAutomorphismKeyMap(kp.secretKey.GetKeyTag())
            weights["evalAtIndexKeys"] = Serialize(evalAtIndexKeys, BINARY)
            weights["indices"] = self.indices

        if not self.is_MultiParty:
            self.mp_public_key = kp.publicKey
        # if debug:
        #     print("Generated CC, key pair, and initial eval keys.")
        #     print("Sending materials to server for distribution.")
        #     print(f"Leader secret key saved to: {workspace_root}/secretkey.bin")
        #     print("------------------------------------------------------------\n")

        return weights

    def exec_keygen_cc_round1(self, dxo, client_name, workspace_root):
        '''Handles the client-side Round 1 of CC-architecture key generation (non-leaders).

        This function is executed by all clients *except* the leader.
        1. Receives the leader's CC, public key, and initial eval keys from the server.
        2. Generates its own multi-party key pair (skC, pkC).
        3. Generates its shares of the evaluation keys.
        4. Saves its secret key (skC) locally.
        5. Returns its public key share and eval key shares to the server for aggregation.
        '''
        if dxo.data["CC"] is None:
            raise Exception(f"{client_name}: Server did not send CC to Clients")
        self.cc = DeserializeCryptoContextString(dxo.data["CC"], BINARY)
        if dxo.data["public_key_share"] is None:
            raise Exception(f"{client_name}: Server did not send public key share to Clients")
        kp = self._cct.MultipartyKeyGen(DeserializePublicKeyString(dxo.data["public_key_share"], BINARY), False, True)
        public_key_share = kp.publicKey
        self.secret_key = kp.secretKey
        weights = {
            "public_key_share": Serialize(public_key_share, BINARY)
        }

        if self.generate_mult_keys:
            evalMultKey = DeserializeEvalKeyString(dxo.data["evalMultKey"], BINARY)
            evalMultKey2 = self._cct.MultiKeySwitchGen(kp.secretKey, kp.secretKey, evalMultKey)
            weights["evalMultKey2"] = Serialize(evalMultKey2, BINARY)
        if self.generate_sum_keys:
            evalSumKeys = DeserializeEvalKeyMapString(dxo.data["evalSumKeys"], BINARY)
            evalSumKeysB = self._cct.MultiEvalSumKeyGen(kp.secretKey, evalSumKeys, kp.publicKey.GetKeyTag())
            weights["evalSumKeysB"] = Serialize(evalSumKeysB, BINARY)
        if self.generate_index_keys:
            evalAtIndexKeys = DeserializeEvalKeyMapString(dxo.data["evalAtIndexKeys"], BINARY)
            indices = dxo.data["indices"]
            evalAtIndexKeysB = self._cct.MultiEvalAtIndexKeyGen(kp.secretKey, evalAtIndexKeys, indices, kp.publicKey.GetKeyTag())
            weights["evalAtIndexKeysB"] = Serialize(evalAtIndexKeysB, BINARY)

        # if debug:
        #     print(f"\n--- [DEBUG] {client_name} (Non-Leader): exec_keygen_cc_round1 ---")
        #     print("Received leader's crypto materials. Generated own key pair and eval key shares.")
        #     print("Sending shares to server for aggregation.")
        #     print(f"Own secret key saved to: {workspace_root}/secretkey.bin")
        #     print("------------------------------------------------------------------\n")

        return weights


    def apply_biomarker_score_postprocess_tail(self, computation_type, cached_cts, metadata, depth_required=None):
        """Split-architecture postprocess: apply the per-slot tail to the producer's cached score.

        The ``biomarker_enc_score_cache`` producer already ran the expensive dot product + pack and
        cached the packed **rsf-scaled** score ciphertext (``rsf*score``; rsf = 1/|cutoff| baked into
        the coeffs so the signal is large during the dot product -> KM sign protection; one per model
        x client, incl. the server's own ``biomarker_server_risk_key`` slice). Each consumer applies
        only its cheap per-slot tail -- NO dot product, NO re-pack:

          * ``biomarker_enc_score_postprocess`` (LCS): homomorphically descale by multiplying with
            the encrypted ``1/rsf`` (``ct x ct``). The cached pack has ``rsf*score`` in each patient's
            slot and 0 elsewhere; multiplying by the broadcast ``1/rsf`` yields ``score`` in the slot
            and leaves empty slots at 0 -- the SAME packed layout the fused scoring path produced, so
            the executor's round-2 extraction is unchanged. The server never sees plaintext ``rsf``.
          * ``biomarker_enc_risk_group_postprocess`` (KM, avenue 3): subtract the baked cutoff
            ``rsf*K`` (= sign(K) broadcast) then multiply by a fresh full-slot multiplicative mask
            ``rm`` -- giving ``rm*rsf*(score - K)``, the same quantity the fused
            ``biomarker_enc_risk_group_computation`` decrypts. The cutoff subtract is additive (no
            level); the ``rm`` multiply is the one tail level.

        Both consumers spend one tail multiply on top of the producer's 3 pack multiplies ->
        depth_required = 5 (with one decrypt-mask margin).

        ``FLEXIBLEAUTO`` auto-levels the fresh cutoff / rm operands onto the depleted cached
        ciphertext. The read is NON-DESTRUCTIVE (a fresh ciphertext is deserialized from the stored
        bytes; the cache dict is not mutated) so a combined KM+LCS job's two consumers can both read
        the same cached score. Returns the same ``({"enc_result": payload}, local_list_enc_result)``
        shape as ``aggregate_stat_analytics`` so the decrypt round is identical to the fused path.

        KNOWN LEAK (KM, avenue 3): the cached score is 0 at padding/unused slots (clients pad with
        zero covariates), so ``- (rsf*K)`` leaves ``-sign(K)`` there and ``* rm`` gives ``-rm*sign(K)``.
        The magnitude is hidden by ``rm`` but the SIGN reveals ``sign(cutoff)``
        (one bit of the model) to a data owner inspecting its own trimmed-off slots. Trimmed by the
        executor extraction before grouping -> passive read-only leak, pre-existing in the fused KM
        path. Accepted for now; the private fix is the encrypted occupancy mask
        (UnifiedBiomarkerScorePlan.md section 9). LCS has no analogue (no cutoff subtraction).
        """
        IS_LCS = (computation_type == ENC_BIOMARKER_SCORE_POSTPROCESS)
        IS_KM = (computation_type == ENC_BIOMARKER_RISK_GROUP_POSTPROCESS)
        if not (IS_LCS or IS_KM):
            raise ValueError(
                f"apply_biomarker_score_postprocess_tail does not support computation_type={computation_type!r}"
            )

        model_keys = list(metadata["model_keys"])
        biomarker_models_by_key = metadata["biomarker_models_by_key"]
        level_val = self.mult_depth - depth_required if depth_required is not None else 0

        # KM only: one fresh full-slot multiplicative mask rm, shared across models/clients (each
        # data owner only ever decrypts its own slice, so a shared draw leaks nothing cross-client),
        # calibrated on the CLIENT count exactly as the fused discovery path (openfhe ~L1428-1448).
        rm_ptxt = None
        if IS_KM:
            client_names = set()
            for per_client in cached_cts.values():
                for cn in per_client.keys():
                    if cn != biomarker_server_risk_key:
                        client_names.add(cn)
            num_clients = len(client_names)
            sigma_val, B_val = self._biomarker_model_mask_params(num_clients)
            scale_val = sigma_val / math.sqrt(num_clients) if num_clients > 0 else sigma_val
            bound = B_val / num_clients if num_clients > 0 else B_val
            z = np.random.normal(0.0, scale_val, size=self.cc_batch_size)
            rm = np.exp(np.clip(z, -bound, bound))
            rm_ptxt = self._cct.MakeCKKSPackedPlaintext(rm.tolist(), level=level_val)

        local_list_enc_result = {}
        for mk in model_keys:
            per_client = cached_cts.get(mk)
            if not per_client:
                raise Exception(
                    f"Score cache is missing model_key={mk!r}; the "
                    f"biomarker_enc_score_cache producer must run before the postprocess consumer."
                )
            paths = biomarker_models_by_key[mk]
            # Shared BAKED cache: the producer cached rsf*score (rsf baked into the coeffs so the
            # signal is large during the dot product -> KM sign protection). LCS homomorphically
            # descales by the encrypted 1/rsf (ct x ct -> raw score); KM subtracts the baked cutoff
            # and masks with rm.
            ctxt_inv_rsf = None
            ctxt_cutoff = None
            if IS_LCS:
                inv_rsf_path = paths.get("inv_rsf_ct_file_path")
                # A baked upload emits the encrypted 1/rsf so LCS can descale rsf*score -> score.
                # An LCS-only (unbaked, rsf=1) upload emits NO 1/rsf: the cache already holds the
                # raw score, so its absence means the descale is skipped (identity) below.
                if inv_rsf_path and os.path.exists(inv_rsf_path):
                    with open(inv_rsf_path, "rb") as f:
                        ctxt_inv_rsf = DeserializeCiphertextString(f.read(), BINARY)
            else:
                cutoff_path = paths.get("cutoff_ct_file_path")
                if not cutoff_path or not os.path.exists(cutoff_path):
                    raise FileNotFoundError(
                        f"Encrypted cutoff artifact missing for model_key={mk!r} "
                        f"({cutoff_path!r}); required for biomarker_enc_risk_group_postprocess."
                    )
                with open(cutoff_path, "rb") as f:
                    ctxt_cutoff = DeserializeCiphertextString(f.read(), BINARY)

            local_list_enc_result[mk] = {}
            for client_name, ser_cts in per_client.items():
                # The cached slice is a LIST of output ciphers (one per cc_batch_size-wide window
                # of that client's cohort). The tail is per-slot, so it applies to each window
                # independently -- rm and the cutoff/1-over-rsf operands are full-slot broadcasts
                # and are reused across windows unchanged.
                out_cts = []
                for ser_ct in _as_cipher_list(ser_cts):
                    # Fresh deserialize -> non-destructive: the cached bytes stay intact for a
                    # sibling consumer (e.g. the KM postprocess in a combined job).
                    cached_ct = DeserializeCiphertextString(ser_ct, BINARY)
                    if IS_LCS:
                        # Baked cache: descale rsf*score by 1/rsf. Unbaked (lcs_only): cache is already
                        # the raw score, so pass it through (no descale multiply).
                        out_ct = self._cct.EvalMult(cached_ct, ctxt_inv_rsf) if ctxt_inv_rsf is not None else cached_ct
                    else:
                        diff_ct = self._cct.EvalSub(cached_ct, ctxt_cutoff)      # rsf*(score - cutoff)
                        out_ct = self._cct.EvalMult(diff_ct, rm_ptxt)            # rm*rsf*(score - cutoff)
                    out_cts.append(out_ct)
                local_list_enc_result[mk][client_name] = out_cts

        payload_ciphers = {
            mk: {cn: serialize_cipherlist(cts) for cn, cts in per_client.items()}
            for mk, per_client in local_list_enc_result.items()
        }
        return {"enc_result": payload_ciphers}, local_list_enc_result


    def exec_get_encrypted_model_weights(self, batched_list):
        '''Encrypts a list of batched model weights and returns the payload.

        This is a standard client task in a training workflow. It takes the local
        model weights (pre-batched), encrypts them using the multi-party public key,
        and returns them for aggregation.
        '''
        payload = {"ciphertext": self.encrypt_batched_list(batched_list)}
        return payload

    def exec_encrypt_stat_analytics(self, round, computation_type, weights, depth_required = None):
        '''Encrypts local statistics for a secure analytics workflow.

        Based on the computation type, it packs the local statistics (e.g., sum, count)
        into a specific format, encrypts them, and returns the payload.
        '''
        self.custom_logger.info(f"Encrypting pre-processed results for computation_type = {computation_type}.")
        level_val = 0
        if depth_required:
            level_val = self.mult_depth - depth_required
            # self.custom_logger.info(f"Encrypted at level: {level_val} for computation_type = {computation_type}.")
        if computation_type == "_PRE_COUNT_UNSECURE_":
            list_ciphers = self.encrypt_list(weights['count'], level_val)
            return {"ciphertext": list_ciphers}
        elif computation_type == "_PRE_COUNT_SECURE_":
            dict_list_ciphers = {}
            for key in ["count", "rm_share"]:
                dict_list_ciphers[key] = self.encrypt_list(weights[key], level_val)
            return {"ciphertext": dict_list_ciphers}
        elif computation_type == "mean":
            list_weights = [weights['sum'], weights['count']]
            list_ciphers = self.encrypt_list(list_weights, level_val)
            return {"ciphertext": list_ciphers}
        elif computation_type == "meta-analysis":
            # 3-slot layout: (w·β₁, w, usable). Slot 2 tree-sums to the number of
            # sites whose local fit passed the gates (>= 2 required to combine).
            list_weights = [weights['sum'], weights['count'], weights.get('usable', 0.0)]
            list_ciphers = self.encrypt_list(list_weights, level_val)
            return {"ciphertext": list_ciphers}
        elif computation_type == "stdev":
            list_weights = [weights['sum_sq'], weights['sum'], weights['count'], weights['sum'], weights['count'], 0]
            list_ciphers = self.encrypt_list(list_weights, level_val)
            return {"ciphertext": list_ciphers}
        elif computation_type == "mean-stdev":
            # Layout (9 slots): [x²_sum, x_sum, n, x_sum, n, 0, x_sum, n, 0].
            # The trailing (x_sum, n, 0) carries the mean payload through the
            # rotate-multiply-subtract pipeline (see aggregate_stat_analytics).
            list_weights = [
                weights['sum_sq'], weights['sum'], weights['count'],
                weights['sum'], weights['count'], 0,
                weights['sum'], weights['count'], 0,
            ]
            list_ciphers = self.encrypt_list(list_weights, level_val)
            return {"ciphertext": list_ciphers}
        elif computation_type == "chi2":
            dict_list_ciphers = {}
            for key in ["cont_table", "row_marg", "col_marg", "zeros_row", "zeros_col", "N_sum"]:
                dict_list_ciphers[key] = self.encrypt_list(weights[key], level_val)
            return {"ciphertext": dict_list_ciphers}
        elif computation_type in ENC_BIOMARKER_DOT_PRODUCT_TYPES:
            # The split score-cache producer encrypts the identical per-patient covariate matrix
            # as discovery/scoring -- only the server-side tail differs -- so it shares this branch.
            # Layer C: reuse the encrypted covariate set across disc_1/disc_score + both models for
            # the same cohort. Key on the Layer-B records identity + level + multiparty key tag; an
            # absent stamp (e.g. records not from the cache) falls through to a normal encrypt.
            cpat_key = None
            rec_key = weights.get("_records_cache_key") if isinstance(weights, dict) else None
            if rec_key is not None:
                try:
                    cpat_key = (rec_key, level_val, self.mp_public_key.GetKeyTag())
                except Exception:
                    cpat_key = None
            if cpat_key is not None:
                with self._cpatients_cache_lock:
                    if cpat_key in self._cpatients_cache:
                        self._cpatients_cache.move_to_end(cpat_key)
                        return {"ciphertext": self._cpatients_cache[cpat_key]}

            all_records = list(weights.get("all_records") or [])
            if not all_records:
                ncols = int(weights.get("record_len", 0) or 0)
                if ncols < 1:
                    return {"ciphertext": []}
                all_records = [[0.0] * ncols]
            num_records = len(all_records)
            len_record = len(all_records[0])
            next_pow_2 = 2**(math.ceil(math.log2(len_record))) if len_record > 0 else 1
            if num_records * next_pow_2 % self.cc_batch_size != 0:  # Padding 0 values at empty slots
                num_pad_empty_vecs = (self.cc_batch_size - (num_records * next_pow_2 % self.cc_batch_size))//next_pow_2
                all_records = all_records + [[0.0] * len_record for _ in range(num_pad_empty_vecs)]
            num_records = len(all_records)

            list_all_records = []
            for record in all_records:
                list_all_records.extend(record + [0]*(next_pow_2 - len_record))
            list_ciphers = self.encrypt_list(list_all_records, level_val)   # Assumption that batch size is always a power of 2 (which is true in ckks)
            if cpat_key is not None:
                with self._cpatients_cache_lock:
                    self._cpatients_cache[cpat_key] = list_ciphers
                    self._cpatients_cache.move_to_end(cpat_key)
                    while len(self._cpatients_cache) > self._cpatients_cache_max:
                        self._cpatients_cache.popitem(last=False)
            return {"ciphertext": list_ciphers}
        elif computation_type == "kaplan-meier":
            dict_dict_list_ciphers = {}
            for group in weights:
                dict_dict_list_ciphers[group] = {}
                for key in weights[group]:
                    dict_dict_list_ciphers[group][key] = self.encrypt_list(weights[group][key], level_val)
            return {"ciphertext": dict_dict_list_ciphers}
        elif computation_type == "t-test":
            categories = list(weights.keys())
            categories.sort()
            list_weights = [
                weights[categories[0]]['sum_sq'],
                weights[categories[0]]['sum'],
                weights[categories[0]]['count'],
                weights[categories[0]]['sum'],
                weights[categories[0]]['count'],
                0, 0, 0,
                weights[categories[1]]['sum_sq'],
                weights[categories[1]]['sum'],
                weights[categories[1]]['count'],
                weights[categories[1]]['sum'],
                weights[categories[1]]['count'],
                0, 0, 0
            ]
            list_weights = list_weights * (self.cc_batch_size//16)  # Repeating values to compute over rotated ciphers.
            list_ciphers = self.encrypt_list(list_weights, level_val)
            return {"ciphertext": list_ciphers}
        else:
            raise ValueError(f"Unsupported computation type: {computation_type}")

    def _decrypt_stat_analytics_single_shares(self, computation_type, enc_result, arch, client_name, is_leader_client = False, decryptor_type = "main"):
        self.custom_logger.info(f"Partial decryption of aggregated results for computation_type = {computation_type}.")
        dec_result = {}

        if computation_type == "_PRE_COUNT_UNSECURE_" or computation_type == "_PRE_COUNT_SECURE_":
            dec_result = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result), arch, is_leader_client, decryptor_type))
        elif computation_type == "mean":
            dec_result = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result), arch, is_leader_client, decryptor_type))

        elif computation_type == "meta-analysis":
            dec_result = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result), arch, is_leader_client, decryptor_type))

        elif computation_type == "stdev":
            dec_result = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result), arch, is_leader_client, decryptor_type))

        elif computation_type == "mean-stdev":
            dec_result = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result), arch, is_leader_client, decryptor_type))

        elif computation_type == "chi2":
            dec_result["numerator"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["numerator"]), arch, is_leader_client, decryptor_type))
            dec_result["denominator"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["denominator"]), arch, is_leader_client, decryptor_type))
            dec_result["dof"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["dof"]), arch, is_leader_client, decryptor_type))

        elif computation_type in ENC_BIOMARKER_DECRYPT_TYPES:
            # Every slice is a LIST of output ciphers (one per cc_batch_size-wide window of the
            # owning client's cohort). The client's OWN slice gets one independent hide-from-lead
            # mask per cipher, keyed (model, cipher index) so each is removed against its own.
            for mk, per_model in enc_result.items():
                dec_result[mk] = {}
                for key, value in per_model.items():
                    cts = [
                        DeserializeCiphertextString(v, BINARY) if isinstance(v, (bytes, str)) else v
                        for v in _as_cipher_list(value)
                    ]
                    if key == client_name:
                        shares = []
                        for idx, ct in enumerate(cts):
                            main_partial_share = self.decrypt_cipherlist(
                                [ct], arch, is_leader_client, decryptor_type
                            )
                            masked_share = self._apply_biomarker_mask(
                                ct, main_partial_share[0], model_key=(mk, idx)
                            )
                            shares.append(Serialize(masked_share, BINARY))
                        dec_result[mk][key] = shares
                    else:
                        dec_result[mk][key] = serialize_cipherlist(
                            self.decrypt_cipherlist(
                                cts,
                                arch,
                                is_leader_client,
                                decryptor_type,
                            )
                        )

        elif computation_type == "kaplan-meier":
            all_group_names = sorted(enc_result["numerator_groups"].keys())

            dec_result["numerator_groups"] = {g: serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["numerator_groups"][g]), arch, is_leader_client, decryptor_type)) for g in all_group_names}
            dec_result["denominator_groups"] = {g: serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["denominator_groups"][g]), arch, is_leader_client, decryptor_type)) for g in all_group_names}
            if len(all_group_names) == 2 and "numerator_A" in enc_result:
                dec_result["numerator_A"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["numerator_A"]), arch, is_leader_client, decryptor_type))
                dec_result["denominator_A"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["denominator_A"]), arch, is_leader_client, decryptor_type))
                dec_result["numerator_var_A"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["numerator_var_A"]), arch, is_leader_client, decryptor_type))
                dec_result["denominator_var_A"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["denominator_var_A"]), arch, is_leader_client, decryptor_type))

        elif computation_type == "t-test":
            dec_result["num_d"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["num_d"]), arch, is_leader_client, decryptor_type))
            dec_result["num_den_d"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["num_den_d"]), arch, is_leader_client, decryptor_type))
            dec_result["den_den_d"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["den_den_d"]), arch, is_leader_client, decryptor_type))
            dec_result["num_t"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["num_t"]), arch, is_leader_client, decryptor_type))
            dec_result["den_t"] = serialize_cipherlist(self.decrypt_cipherlist(deserialize_cipherlist(enc_result["den_t"]), arch, is_leader_client, decryptor_type))

        else:
            raise ValueError(f"Unsupported computation type: {computation_type}")

        if not self.is_MultiParty:
            return dec_result
        return {"partialresult": dec_result}

    def _apply_biomarker_mask(self, ctxt, partial_share, model_key):
        '''Apply a fresh hide-from-lead additive mask, keyed by model_key.

        ``model_key`` is a ``(model, output_cipher_index)`` tuple when a cohort spans several
        output ciphers, so each cipher carries its own independent mask.
        '''
        if model_key in self.biomarker_decrypt_masks:
            raise Exception(
                f"Random mask already generated for model_key={model_key!r}; cannot generate another."
            )
        mask = self._cct.IntMPBootRandomElementGen(ctxt)
        self.biomarker_decrypt_masks[model_key] = mask
        self._cct.EvalAddInPlace(partial_share, mask)
        return partial_share

    def _remove_biomarker_mask_and_extract_scores(self, ser_ctxt_risk_scores, model_key, remove_mask=True):
        '''Finalize multiparty decryption of a biomarker risk-score slice and return the scores.

        Clients call this for their OWN slice with remove_mask=True: a random additive mask was
        applied during round 1 (to hide their plaintext scores from the server during fusion),
        so it must be removed before the final MultipartyDecryptFusion. The SERVER calls this for
        its own slice (biomarker_server_risk_key) with remove_mask=False: the server is the
        legitimate owner of that slice, so no hide-from-lead mask was ever applied to it.

        Returns a LIST of decoded slot windows, one per output cipher (a cohort larger than
        cc_batch_size patients spans several). Feed it to
        ``_re_map_batched_patients_biomarker`` to get the flat, in-order per-patient scores.
        '''
        slices = []
        for idx, ser_ct in enumerate(_as_cipher_list(ser_ctxt_risk_scores)):
            ctxt_risk_scores = DeserializeCiphertextString(ser_ct, BINARY)
            if remove_mask:
                # Masks are keyed (model, cipher index); fall back to the bare model_key so a
                # single-cipher payload from an older peer still decrypts.
                mask_key = (model_key, idx)
                if mask_key not in self.biomarker_decrypt_masks:
                    mask_key = model_key
                if mask_key not in self.biomarker_decrypt_masks:
                    raise Exception(
                        f"No random mask for model_key={model_key!r} (cipher {idx}). Cannot remove mask."
                    )
                mask = self.biomarker_decrypt_masks.pop(mask_key)
                self._cct.EvalAddInPlace(ctxt_risk_scores, self._cct.EvalNegate(mask))
            plaintext = self._cct.MultipartyDecryptFusion([ctxt_risk_scores])

            if self.ckks_data_type == "COMPLEX":
                slices.append(UnpackFullComplex(plaintext.GetCKKSPackedValue()).tolist())
            else:
                slices.append(list(plaintext.GetRealPackedValue()))

        # One entry per output cipher: a self-contained cc_batch_size-wide window of the cohort.
        # _re_map_batched_patients_biomarker turns these back into a flat, in-order score list.
        return slices

# ---------------------------------------------------------------------------------
# Global Helper for Parallelization
# ---------------------------------------------------------------------------------

# Global variables to store the heavy context within each worker process
WORKER_CC = None

# Biomarker ProcessPool RAM budget (Linux MemAvailable). Tune BASE / PER_WORKER MiB from measured RSS if needed.
# Env: OPENFHE_BIOMARKER_MAX_WORKERS — if set (positive int), skip auto and use this value.
# Env: OPENFHE_BIOMARKER_BASE_RAM_MB — parent + main OpenFHE + SHM mapping overhead (conservative static budget).
# Env: OPENFHE_BIOMARKER_PER_WORKER_RAM_MB — incremental RSS per worker after worker_init (conservative).
# Env: OPENFHE_BIOMARKER_OS_RESERVE_MB — leave headroom for OS / NVFlare / cache reclaim.
# Env: OPENFHE_BIOMARKER_MAX_WORKERS_CAP — upper bound for auto mode.
# Env: OPENFHE_BIOMARKER_MAX_WORKERS_MEM_FALLBACK — when /proc/meminfo is unavailable.
_BIOMARKER_RAM_BASE_MB_DEFAULT = 1536
_BIOMARKER_RAM_PER_WORKER_MB_DEFAULT = 1536
_BIOMARKER_RAM_OS_RESERVE_MB_DEFAULT = 512
_BIOMARKER_MAX_WORKERS_CAP_DEFAULT = 72
_BIOMARKER_MAX_WORKERS_MEM_FALLBACK = 10

def resolve_biomarker_max_workers(logger) -> int:
    """
    MAX_WORKERS = min(cpu_cores, cap, max(1, (MemAvailable - base - reserve) // per_worker)).

    The CPU-core term keeps the count from exceeding the cores (the HE section is
    core-bound, so extra workers waste RAM without speeding it up). Override
    entirely with OPENFHE_BIOMARKER_MAX_WORKERS=<int> (honored verbatim, not
    core-capped). Static MiB defaults are conservative — adjust from measured
    VmRSS (parent vs worker after init).
    """
    fixed_raw = os.environ.get("OPENFHE_BIOMARKER_MAX_WORKERS")
    if fixed_raw is not None and str(fixed_raw).strip():
        try:
            fixed = int(str(fixed_raw).strip(), 10)
            if fixed >= 1:
                logger.info(
                    "biomarker_enc_risk_group_computation: MAX_WORKERS=%s (OPENFHE_BIOMARKER_MAX_WORKERS override).",
                    fixed,
                )
                return fixed
        except ValueError:
            pass

    cpu_n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)

    def _env_positive_int(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            v = int(str(raw).strip(), 10)
            return v if v > 0 else default
        except ValueError:
            return default

    base_mb = _env_positive_int("OPENFHE_BIOMARKER_BASE_RAM_MB", _BIOMARKER_RAM_BASE_MB_DEFAULT)
    per_mb = _env_positive_int("OPENFHE_BIOMARKER_PER_WORKER_RAM_MB", _BIOMARKER_RAM_PER_WORKER_MB_DEFAULT)
    reserve_mb = _env_positive_int("OPENFHE_BIOMARKER_OS_RESERVE_MB", _BIOMARKER_RAM_OS_RESERVE_MB_DEFAULT)
    cap = _env_positive_int("OPENFHE_BIOMARKER_MAX_WORKERS_CAP", _BIOMARKER_MAX_WORKERS_CAP_DEFAULT)
    fallback = _env_positive_int("OPENFHE_BIOMARKER_MAX_WORKERS_MEM_FALLBACK", _BIOMARKER_MAX_WORKERS_MEM_FALLBACK)

    base_b = base_mb * 1024 * 1024
    per_b = per_mb * 1024 * 1024
    reserve_b = reserve_mb * 1024 * 1024

    def read_linux_memavailable_bytes() -> Optional[int]:
        """Linux MemAvailable from /proc/meminfo (kB -> bytes). Best single metric for 'usable RAM'."""
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        return int(parts[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    avail = read_linux_memavailable_bytes()
    if avail is None:
        n = min(fallback, cap, cpu_n)
        logger.info(
            "biomarker_enc_risk_group_computation: MemAvailable unavailable; MAX_WORKERS=%s "
            "(min of OPENFHE_BIOMARKER_MAX_WORKERS_MEM_FALLBACK, cap, cores=%s).",
            n,
            cpu_n,
        )
        return max(1, n)

    budget = avail - base_b - reserve_b
    if budget <= 0:
        logger.warning(
            "biomarker_enc_risk_group_computation: MemAvailable after base+reserve non-positive; MAX_WORKERS=1 "
            "(MemAvailable=%.2f MiB, base=%s MiB, os_reserve=%s MiB).",
            avail/1024.0/1024.0,
            base_mb,
            reserve_mb,
        )
        return 1

    n = max(1, budget // per_b)
    n = min(n, cap, cpu_n)
    logger.info(
        "biomarker_enc_risk_group_computation: MAX_WORKERS=%s = min(cores=%s, cap=%s, mem-budget) from "
        "MemAvailable=%.2f MiB, budget formula: (avail - base=%s MiB - os_reserve=%s MiB) // per_worker=%s MiB.",
        n,
        cpu_n,
        cap,
        avail/1024.0/1024.0,
        base_mb,
        reserve_mb,
        per_mb,
    )
    return n

def create_shm(data_bytes):
    '''Helper to create a shared memory block and write data into it.'''
    shm = shared_memory.SharedMemory(create=True, size=len(data_bytes))
    shm.buf[:len(data_bytes)] = data_bytes
    return shm

def worker_init_biomarker(shm_names, sizes, level_val):
    """Load CryptoContext and eval keys once per worker (model coeffs are passed per task)."""
    global WORKER_CC

    # Each worker is a separate process with its own totals; startup cost (context and
    # eval-key deserialisation) is real OpenFHE time and is counted here.
    fhe_timing.reset()
    # Record busy intervals here so the parent can union them across workers; a
    # worker is single-threaded, so its own intervals are already disjoint.
    fhe_timing.enable_intervals(True)

    shm_cc = shared_memory.SharedMemory(name=shm_names["cc"])
    shm_multkey = shared_memory.SharedMemory(name=shm_names["multkey"])
    shm_indexkey = shared_memory.SharedMemory(name=shm_names["indexkeys"])

    WORKER_CC = DeserializeCryptoContextString(bytes(shm_cc.buf[: sizes["cc"]]), BINARY)
    WORKER_CC = fhe_timing.TimedProxy(WORKER_CC, "cc.")
    WORKER_CC.InsertEvalMultKey(
        [DeserializeEvalKeyString(bytes(shm_multkey.buf[: sizes["multkey"]]), BINARY)]
    )
    WORKER_CC.InsertEvalAutomorphismKey(
        DeserializeEvalKeyMapString(bytes(shm_indexkey.buf[: sizes["indexkeys"]]), BINARY)
    )

    shm_cc.close()
    shm_multkey.close()
    shm_indexkey.close()

    # Best-effort: log this worker's resident memory after loading CC + eval keys. This is the
    # per-worker RAM that bounds how many workers fit (MAX_WORKERS); it grows with the rotation-key
    # set size. May be silent if child-process logs are not captured -- the main process also logs
    # len(indexkeys) as a reliable proxy for the rotation-key share of this footprint.
    try:
        with open("/proc/self/status", encoding="utf-8") as _f:
            for _line in _f:
                if _line.startswith("VmRSS:"):
                    logging.getLogger("custom.audit_log").info(
                        "biomarker worker init: pid=%s VmRSS=%s (indexkeys=%s bytes)",
                        os.getpid(), _line.split(":", 1)[1].strip(), sizes.get("indexkeys"),
                    )
                    break
    except OSError:
        pass


def _func_risk_score_multi_model_batch(
    model_keys,
    ser_models,
    list_ser_c_patient,
    mask_full,
    list_shift_mask_item,
    cov_length,
    level_val,
    is_model_encrypted,
    skip_cutoff=False,
    list_out_idx=None,
):
    """Compute risk-score ciphertexts for all models over the same patient ciphertext chunk.

    When ``skip_cutoff=True`` (the score-cache producer) the cutoff subtraction is omitted so
    the output cipher carries ``rsf·score`` instead of ``rsf·(score − cutoff)``; the packed
    ``rsf``-scaled score is cached for the postprocess consumers to descale/threshold.

    ``list_out_idx[i]`` is the index of the output cipher that patient cipher ``i`` belongs to
    (``patient_cipher_index // cov_length``; see the packing note in aggregate_stat_analytics).
    A chunk may straddle an output-cipher boundary, so results are accumulated per output index
    and the return value is ``{model_key: {out_idx: serialized_cipher}}``. Defaults to all-zeros
    (single output cipher), which is the behaviour for any cohort up to cc_batch_size patients.
    """
    global WORKER_CC
    _fhe_before = fhe_timing.snapshot()

    c_patients = [DeserializeCiphertextString(s, BINARY) for s in list_ser_c_patient]
    ptxt_mask = WORKER_CC.MakeCKKSPackedPlaintext(mask_full, level=level_val)
    # cov_length is a power of two; precompute the doubling rotation offsets [1, 2, 4, ...] once. These
    # were recomputed in the hot loop (int(math.log2(cov_length)) twice per patient + 2**j each step).
    rot_steps = [1 << j for j in range(int(math.log2(cov_length)))]
    # §1.1: the shift mask depends only on the patient-chunk index, not the model, so encode the
    # distinct shift-mask plaintexts once here and reuse them across every model below. Previously
    # this was re-encoded inside the per-model x per-patient loop (len(model_keys) x len(c_patients)
    # full encodes); a plaintext passed to EvalMult is not mutated, so reuse is safe (same pattern
    # as ptxt_mask above).
    ptxt_shift_masks = [
        WORKER_CC.MakeCKKSPackedPlaintext(shift_mask_item, level=level_val)
        for shift_mask_item in list_shift_mask_item
    ]
    if list_out_idx is None:
        list_out_idx = [0] * len(c_patients)
    out = {}

    for mk, (ser_coeff, ser_cutoff) in zip(model_keys, ser_models):
        if is_model_encrypted:
            ctxt_coeff = DeserializeCiphertextString(ser_coeff, BINARY)
            ctxt_cutoff = DeserializeCiphertextString(ser_cutoff, BINARY)
        else:
            ctxt_coeff = WORKER_CC.MakeCKKSPackedPlaintext(
                pickle.loads(ser_coeff), level=level_val
            )
            ctxt_cutoff = WORKER_CC.MakeCKKSPackedPlaintext(
                pickle.loads(ser_cutoff), level=level_val
            )

        # Masks that place each patient's score into its output slot. Discovery and the
        # neutral score_cache producer apply the plaintext shift/rm masks directly (ct x pt);
        # the LCS descale is done later by the postprocess consumer, not here.
        packing_masks = ptxt_shift_masks

        batch_sums = {}
        for i, c_patient in enumerate(c_patients):
            # 2. Compute matrix-vector mult
            cipher = WORKER_CC.EvalMult(c_patient, ctxt_coeff)
            # 3. Rotate and add (Accumulate)
            for step in rot_steps:
                cipher = WORKER_CC.EvalAdd(cipher, WORKER_CC.EvalRotate(cipher, step))
            # 4. Mask
            cipher = WORKER_CC.EvalMult(cipher, ptxt_mask)
            # 5. Shift result right
            cipher = WORKER_CC.EvalRotate(cipher, -(cov_length - 1))
            # 6. Repeat result
            for step in rot_steps:
                cipher = WORKER_CC.EvalAdd(cipher, WORKER_CC.EvalRotate(cipher, step))
            # 7. Subtract cutoff (skipped for the score-only LCS path)
            if not skip_cutoff:
                WORKER_CC.EvalSubInPlace(cipher, ctxt_cutoff)
            # 8. Apply the packing mask (LCS: ct x ct, with 1/rsf folded in -> raw score)
            cipher = WORKER_CC.EvalMult(cipher, packing_masks[i])
            # 9. Aggregate locally, per output cipher (a chunk may span two of them)
            oc = list_out_idx[i]
            if oc not in batch_sums:
                batch_sums[oc] = cipher
            else:
                WORKER_CC.EvalAddInPlace(batch_sums[oc], cipher)

        out[mk] = {oc: Serialize(ct, BINARY) for oc, ct in batch_sums.items()}

    return out, (os.getpid(), fhe_timing.delta_since(_fhe_before),
                 fhe_timing.intervals_snapshot())

# ---------------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------------

def _as_cipher_list(value):
    '''Normalizes a biomarker score slice to a list of ciphers (or serialized ciphers).

    A slice used to be a single ciphertext, because one output cipher held the whole cohort.
    Cohorts larger than cc_batch_size now produce a list of them. Tolerating both shapes keeps
    a payload produced by an older peer (or the single-cipher postprocess path) readable.
    '''
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def serialize_cipherlist(cipherlist):
    '''Serializes a list of ciphertexts into a list of bytes.'''
    return [Serialize(cipher, BINARY) for cipher in cipherlist]

def deserialize_cipherlist(serialized_cipherlist):
    '''Deserializes a list of bytes (or str) into a list of ciphertexts.
    If an element is already a Ciphertext (e.g. from in-memory aggregation),
    it is returned as-is.'''
    result = []
    for cipher in serialized_cipherlist:
        if isinstance(cipher, (bytes, str)):
            result.append(DeserializeCiphertextString(cipher, BINARY))
        else:
            # Already a Ciphertext object (e.g. local_list_enc_result from aggregate_stat_analytics)
            result.append(cipher)
    return result

def UnpackFullComplex(complexVec):
    '''Unpacks a complex vector into a real vector by concatenating real and imaginary parts.'''
    complexVec = np.array(complexVec, dtype=complex)
    return np.concatenate((complexVec.real, complexVec.imag))

def PackFullComplex(realVec, maxBatchSize):
    '''Packs a real-valued vector into a complex-valued vector for CKKS encryption.

    This method doubles the data packing capacity for real numbers in CKKS by
    using both the real and imaginary parts of the complex plaintext slots.

    Args:
        realVec (list[float]): The input list of real numbers.
        maxBatchSize (int): The maximum number of complex numbers per ciphertext.

    Returns:
        A NumPy array of complex numbers ready for `MakeCKKSPackedPlaintext`.
    '''
    n = len(realVec)
    # maxBatchSize = int(N/2)
    if n < maxBatchSize:
        return realVec

    realVec = np.array(realVec, dtype=float)
    realPart = realVec[:maxBatchSize]
    imagPart = realVec[maxBatchSize:]
    if len(imagPart) < maxBatchSize:
        imagPart = np.pad(imagPart, (0, maxBatchSize - len(imagPart)))
    complexVec = realPart + 1j * imagPart
    return complexVec

# TODO: Estimate the noise of the decoded plaintext (after decrypt). Not possible with FullPacking.
    # double noise = noisePlaintext->GetLogError();
    # std::cout << "Noise \n\t" << noise << std::endl;
