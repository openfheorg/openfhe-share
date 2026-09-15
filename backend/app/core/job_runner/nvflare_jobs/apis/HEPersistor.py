import logging
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey
from nvflare.app_common.abstract.model_persistor import ModelPersistor
from nvflare.app_common.abstract.model import ModelLearnable, make_model_learnable

from .openfhe_manager import OpenfheManager
from openfhe import *

from . import fhe_timing

fhe_timing.wrap_module_callables(globals(), (
    "Serialize", "DeserializeCryptoContextString", "DeserializePublicKeyString",
    "DeserializePrivateKeyString", "DeserializeEvalKeyString",
    "DeserializeEvalKeyMapString", "DeserializeCiphertextString",
), prefix="fhe.")

class HEPersistor(ModelPersistor):
    """
    An NVFlare ModelPersistor for handling persistence and key management in Homomorphic Encryption (HE) workflows.

    This class is responsible for:
    - Initializing the OpenFHE cryptographic context and keys.
    - Providing the server's secret key to the aggregator (in 'star' architecture).
    - Loading initial cryptographic materials for clients (in 'init_mix_SAG' and 'workflow_KeyGen').
    - Saving the final CryptoContext after key generation.
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(
        self,
        arch = "star",
        hide_result_from_server: bool = False,
        leader_client_name: str = "site1",
        exclude_analyzing_clients=None,
        mult_depth = 0,
        cc_batch_size = None,
        scale_mod_size = 53,
        scaling_technique = "FLEXIBLEAUTO",
        key_switch_technique = "BV",
        ckks_data_type = "REAL",
        generate_mult_keys: bool = False,
        generate_sum_keys: bool = False,
        generate_index_keys: bool = False,
        indices: list = [],
    ):
        """
        Initializes the HEPersistor with OpenFHE parameters.

        Args:
            arch (str): The key generation architecture to use ('star' or 'cc').
            mult_depth (int): The multiplicative depth for the CKKS scheme.
            cc_batch_size (int): The batch size for the CryptoContext.
            scale_mod_size (int): The bit-length of the scaling factor.
            scaling_technique (str): The CKKS scaling technique to use.
            key_switch_technique (str): The CKKS key switching technique to use.
            ckks_data_type (str): The data type for CKKS operations ("REAL" or "COMPLEX").
            generate_mult_keys (bool): If True, generate evaluation keys for multiplication.
            generate_sum_keys (bool): If True, generate evaluation keys for summations.
            generate_index_keys (bool): If True, generate evaluation keys for rotations.
            indices (list): A list of indices required for rotation keys.
            exclude_analyzing_clients (list[str] | None): Client names that must not receive the final stat-analytics result.
        """
        self.custom_logger = logging.getLogger("custom.audit_log")

        super().__init__()

        self.openfhe_manager = OpenfheManager(
            mult_depth=mult_depth,
            cc_batch_size=cc_batch_size,
            scale_mod_size=scale_mod_size,
            scaling_technique=scaling_technique,
            key_switch_technique=key_switch_technique,
            ckks_data_type=ckks_data_type,
            generate_mult_keys=generate_mult_keys,
            generate_sum_keys=generate_sum_keys,
            generate_index_keys=generate_index_keys,
            indices=indices,
            is_MultiParty=True
        )

        self.arch = arch
        self.hide_result_from_server = hide_result_from_server
        self.leader_client_name = leader_client_name
        _exc = exclude_analyzing_clients or []
        if not isinstance(_exc, (list, tuple)):
            raise TypeError("exclude_analyzing_clients must be a list of client name strings")
        self.exclude_analyzing_clients = [str(x) for x in _exc]
        if self.leader_client_name in self.exclude_analyzing_clients:
            raise ValueError("leader_client_name cannot appear in exclude_analyzing_clients")
        self.pqc_key_packages = None  # Set after KeyGen when hide_result_from_server; used for first post-KeyGen workflow.

    def get_aggregator_sk(self):
        """
        Provides the server's secret key (generated during Star KeyGen) to the Aggregator.

        This method is typically called by the Aggregator to obtain the secret key
        it needs to participate in multi-party decryption or other key-dependent operations.

        Returns:
            The OpenFHE secret key object.

        Raises:
            Exception: If the secret key has not been generated yet.
        """
        if self.openfhe_manager.kp.secretKey is None:
            raise Exception("Cannot set the Lead secret key")
        return self.openfhe_manager.kp.secretKey

    def load_model(self, fl_ctx: FLContext) -> ModelLearnable:
        """
        Loads initial cryptographic models or parameters for the workflow.

        This method is called by NVFlare to provide initial data to the clients
        or to set up the server's cryptographic context. Its behavior depends
        on the current workflow name.

        Args:
            fl_ctx (FLContext): The current federated learning context.

        Returns:
            ModelLearnable: A ModelLearnable object containing the initial
                            cryptographic parameters or an empty model.
        """
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)

        if workflow_name == "init_mix_SAG":
            if (len(fl_ctx.get_engine().get_clients()) <= 1):
                self.openfhe_manager.is_MultiParty = False
                self.custom_logger.info("Single client detected. Disabling multi-party features for init_mix_SAG.")
            self.openfhe_manager.initialize_openfhe()
            return make_model_learnable(weights={"CC": Serialize(self.openfhe_manager.cc, BINARY)}, meta_props={"arch": self.arch, "cc_batch_size": self.openfhe_manager.cc_batch_size})

        elif workflow_name == "workflow_KeyGen":
            if self.arch == "star":
                self.openfhe_manager.initialize_openfhe()
                self.openfhe_manager.keygen()
                self.custom_logger.info(f"SEND: to all clients + server: Cryptocontext and initial keys.")
                meta = {
                        "round": 0, "arch": self.arch,
                        "mult_depth": self.openfhe_manager.mult_depth,
                        "cc_batch_size": self.openfhe_manager.cc_batch_size,
                        "ckks_data_type": self.openfhe_manager.ckks_data_type,
                        "hide_result_from_server": self.hide_result_from_server,
                        "leader_client_name": self.leader_client_name,
                        "exclude_analyzing_clients": list(self.exclude_analyzing_clients),
                        }
                return make_model_learnable(weights=self.openfhe_manager.serialize_dict(), meta_props=meta)
            elif self.arch == "cc":
                return make_model_learnable(weights={}, meta_props={"round": 0})
            else:
                raise Exception(f"Unsupported architecture {self.arch}")

        return None

    def save_model(self, model: ModelLearnable, fl_ctx: FLContext):
        """
        Saves the CryptoContext received from the aggregator after key generation.

        This method is called by NVFlare to persist the final CryptoContext
        after the distributed key generation process is complete.

        Args:
            model (ModelLearnable): The ModelLearnable object containing the
                                    serialized CryptoContext.
            fl_ctx (FLContext): The current federated learning context.
        """
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        if workflow_name in ["init_mix_SAG", "workflow_KeyGen"]:
            self.openfhe_manager.cc = DeserializeCryptoContextString(model['weights']['CC'], BINARY)
            # PQC routing: persist key packages for server to route to each client in the next workflow.
            if self.hide_result_from_server and workflow_name == "workflow_KeyGen":
                self.pqc_key_packages = model["weights"].get("pqc_key_packages") or {}
