import logging
from nvflare.apis.executor import Executor
from nvflare.apis.shareable import Shareable, make_reply
from nvflare.apis.signal import Signal
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey, ReturnCode
from nvflare.apis.dxo import DXO, DataKind, from_shareable

from .openfhe_manager import OpenfheManager
from .pqc_routing_manager import PQCRoutingManager
from .stat_analytics_event_type import StatAnalyticsEventType
from .HEAggregator import (
    KEY_CLIENT_PQC_PUBLIC_KEYS,
    KEY_PQC_KEY_PACKAGE,
    KEY_PQC_KEY_PACKAGES,
    KEY_PQC_PUBLIC_KEY,
)

class HEExecutor(Executor):
    """
    An NVFlare Executor for handling the client-side logic of HE workflows.

    This class manages the client's participation in complex cryptographic
    protocols like distributed key generation and multi-party decryption. It
    receives tasks from the server (via the HEAggregator) and uses the
    OpenfheManager to perform the necessary client-side cryptographic operations.
    """
    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(
        self,
        # OpenFHE parameters
        leader_client_name: str = "site1",
        mult_depth = 0,
        cc_batch_size = None,
        scale_mod_size = 53,
        scaling_technique = "FLEXIBLEAUTO",  # Pass them as strings to avoid circular import
        key_switch_technique = "BV",
        ckks_data_type = "REAL",
        generate_mult_keys: bool = False,
        generate_sum_keys: bool = False,
        generate_index_keys: bool = False,
        indices: list = [],
    ):
        '''Initializes the client-side Executor for HE-based workflows.

        This constructor configures the underlying OpenfheManager with the
        necessary cryptographic parameters for the CKKS scheme.

        Args:
            leader_client_name (str): The name of the client designated as the "leader"
                                      for the 'cc' (client-contributed) key generation architecture.
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
        '''
        self.custom_logger = logging.getLogger("custom.audit_log")

        super().__init__()
        self.leader_client_name = leader_client_name
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

        self.arch = None
        self.hide_result_from_server = None
        self.exclude_analyzing_clients = []
        self._pqc_manager = None
        self.local_partial_decrypt_share = None

    def _get_pqc_manager(self, client_name: str):
        """Lazy-init PQC routing manager (coordinator for lead client, standard client otherwise)."""
        if self._pqc_manager is None and self.hide_result_from_server:
            self._pqc_manager = PQCRoutingManager(
                client_name=client_name,
                is_coordinator=(client_name == self.leader_client_name),
            )
        return self._pqc_manager

    def execute(self, task_name: str, shareable: Shareable, fl_ctx: FLContext, abort_signal: Signal) -> Shareable:
        """
        The main entry point for the executor, called by the NVFlare framework for each task.

        This method acts as a router, dispatching incoming tasks from the server
        to the appropriate handler method based on the task name.

        Args:
            task_name (str): The name of the task to be executed.
            shareable (Shareable): The data received from the server.
            fl_ctx (FLContext): The current federated learning context.
            abort_signal (Signal): A signal to check for abort requests.

        Returns:
            A Shareable object containing the results of the task execution.
        """
        self.custom_logger.info(f"[{fl_ctx.get_prop(ReservedKey.CLIENT_NAME)}] Received task: '{task_name}'")

        dxo = from_shareable(shareable)
        if task_name == "task_init_mix":
            return self._task_init_mix(dxo, fl_ctx)
        elif task_name == "task_KeyGen":
            if dxo.get_meta_prop("round") == 0:
                self.arch = dxo.get_meta_prop("arch")
                self.hide_result_from_server = dxo.get_meta_prop("hide_result_from_server")
                # Server-fed value from persistor (single source in server config)
                leader = dxo.get_meta_prop("leader_client_name")
                if leader is not None:
                    self.leader_client_name = leader
                exc = dxo.get_meta_prop("exclude_analyzing_clients")
                self.exclude_analyzing_clients = [str(x) for x in exc] if isinstance(exc, (list, tuple)) else []
            return self._task_KeyGen(dxo, fl_ctx)
        # If the task is not handled here, a child class might handle it.
        return None

    # ------------------------------------------------------------------
    # Task: task_init_mix
    # ------------------------------------------------------------------
    def _task_init_mix(self, dxo, fl_ctx):
        """
        Handles the task for initializing the CryptoContext in a 'mix' architecture.

        In this workflow, the server generates the CryptoContext and sends it to all
        clients. This method receives and saves it locally.
        """
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        workspace_root = fl_ctx.get_prop(ReservedKey.WORKSPACE_ROOT)
        self.custom_logger.info(f"[{client_name}] Executing task_init_mix: receiving and saving CryptoContext.")
        self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
        try:
            ser_weights = self.openfhe_manager.exec_init_mix(dxo, client_name, workspace_root)
        finally:
            self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
        return self.get_shareable_data(ser_weights, fl_ctx)

    # ------------------------------------------------------------------
    # Task: KeyGen
    # ------------------------------------------------------------------
    def _task_KeyGen(self, dxo, fl_ctx):
        """
        Handles the client's role in the multi-round key generation process.

        The logic branches based on the key generation architecture ('star' or 'cc')
        and the current round of the protocol.
        """
        round = dxo.get_meta_prop("round")
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        workspace_root = fl_ctx.get_prop(ReservedKey.WORKSPACE_ROOT)
        ser_weights = {}
        self.custom_logger.info(f"[{client_name}] Executing KeyGen, architecture: '{self.arch}', round: {round}.")

        if self.arch == "star":
            if round == 0:
                # Generate and send this client's public key and eval key shares.
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_weights = self.openfhe_manager.exec_keygen_star_round0(dxo, client_name, workspace_root)
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
                # PQC routing: standard clients send their ML-KEM public key for later key package delivery.
                if (
                    self.hide_result_from_server
                    and client_name != self.leader_client_name
                    and client_name not in self.exclude_analyzing_clients
                ):
                    pqc = self._get_pqc_manager(client_name)
                    if pqc is not None:
                        ser_weights[KEY_PQC_PUBLIC_KEY] = pqc.get_public_key()
            elif round == 1:
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    # Lead client: register received PQC public keys and generate key packages for server to route.
                    if self.hide_result_from_server and client_name == self.leader_client_name:
                        client_pubs = (dxo.data or {}).get(KEY_CLIENT_PQC_PUBLIC_KEYS)
                        if client_pubs:
                            pqc = self._get_pqc_manager(client_name)
                            if pqc is not None:
                                for name, pub in client_pubs.items():
                                    if name in self.exclude_analyzing_clients:
                                        continue
                                    pqc.register_pubkey(name, pub)
                                key_packages = pqc.generate_and_distribute_keys(
                                    exclude_clients=set(self.exclude_analyzing_clients)
                                )
                                ser_weights[KEY_PQC_KEY_PACKAGES] = key_packages
                    # Generate and send the final evaluation key share.
                    star_weights = self.openfhe_manager.exec_keygen_star_round1(dxo, client_name, workspace_root)
                    ser_weights = {**star_weights, **ser_weights} if ser_weights else star_weights
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            else:
                raise Exception(f"{client_name}: Invalid round {round}")
        elif self.arch == "cc":
            if round == 0:
                if (len(fl_ctx.get_engine().all_clients) <= 1):
                    self.openfhe_manager.is_MultiParty = False
                # Only the leader client acts in round 0.
                if (client_name == self.leader_client_name):
                    self.custom_logger.info(f"[{client_name}] Acting as leader: generating and sending initial CC and keys.")
                    self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                    try:
                        ser_weights = self.openfhe_manager.exec_keygen_cc_round0(client_name, workspace_root)
                    finally:
                        self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            elif round == 1:
                # Only non-leader clients act in round 1.
                if (client_name != self.leader_client_name):
                    self.custom_logger.info(f"[{client_name}] Acting as non-leader: generating and sending key shares.")
                    self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                    try:
                        ser_weights = self.openfhe_manager.exec_keygen_cc_round1(dxo, client_name, workspace_root)
                    finally:
                        self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            elif round == 2:
                # All clients generate their final evaluation key share.
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_weights = self.openfhe_manager.exec_keygen_star_round1(dxo, client_name, workspace_root)
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            else:
                raise Exception(f"{client_name}: Invalid round {round}")
        else:
            raise Exception(f"{client_name}: Unsupported architecture '{self.arch}'")
        return self.get_shareable_data(ser_weights, fl_ctx)


    # ------------------------------------------------------------------
    # Task: Decryption
    # ------------------------------------------------------------------
    def _Decryption_r0(self, dxo, fl_ctx):
        '''Handles the first round of decryption on the client side.

        This method receives the aggregated encrypted result from the server.
        It then computes and returns its partial decryption share. If not in
        multi-party mode, it performs a direct single-key decryption.
        '''
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        self.custom_logger.info(f"[{client_name}] Executing Decryption round 0.")
        enc_result = dxo.data["enc_result"]
        if self.openfhe_manager.is_MultiParty == False: # must be cc arch
            self.custom_logger.info(f"[{client_name}] Performing single-key decryption.")
            list_result = self.openfhe_manager.OLD_decrypt_singlekey_cipherlist(enc_result)
            return list_result  # This is the final result, ready for post-processing.

        self.custom_logger.info(f"[{client_name}] Generating partial decryption share.")
        ser_weights = self.openfhe_manager.OLD_decrypt_cipherlist(client_name, self.leader_client_name, self.arch, enc_result)
        return self.get_shareable_data(ser_weights, fl_ctx)

    def _Decryption_r1(self, dxo, fl_ctx):
        '''Handles the second and final round of decryption.

        The behavior depends on the architecture. In 'star', the server performs
        the final fusion, so the client just receives the plaintext result. In 'cc',
        a designated client may be responsible for the final fusion.
        '''
        client_name = fl_ctx.get_prop(ReservedKey.CLIENT_NAME)
        self.custom_logger.info(f"[{client_name}] Executing Decryption round 1.")

        if self.arch == "star":
            # The server did the fusion; this is the final plaintext result.
            self.custom_logger.info(f"[{client_name}] Received fully decrypted msg from server.")
            return dxo.data["result"]
        elif self.arch == "cc":
            # This client is responsible for fusing all partial decryption shares.
            self.custom_logger.info(f"[{client_name}] Combining all partial decryption shares.")
            list_result = self.openfhe_manager.decrypt_all_partial_decrypts(dxo.data["list_partialresult"])
            return list_result
        else:
            raise Exception(f"{client_name}: Unsupported architecture '{self.arch}'")


    @staticmethod
    def get_shareable_data(data, fl_ctx: FLContext, metadata={}) -> Shareable:
        '''Creates a DXO of DataKind.WEIGHTS and converts it to a Shareable object.

        This is a helper utility to consistently package data for transmission
        within the NVFlare framework.
        '''
        dxo = DXO(data_kind=DataKind.WEIGHTS, data=data, meta=metadata)
        shareable = dxo.to_shareable()
        return shareable
