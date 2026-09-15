import logging
from typing import Any, Dict, Optional

from nvflare.app_common.abstract.aggregator import Aggregator
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey, ReturnCode
from nvflare.apis.shareable import Shareable
from nvflare.apis.dxo import DXO, DataKind, from_shareable
from nvflare.app_common.app_constant import AppConstants

from .openfhe_manager import OpenfheManager
from .stat_analytics_event_type import StatAnalyticsEventType

# Metadata key for per-client payload specs (asymmetric distribution).
# When present, the workflow sends a tailored payload per client; all clients are contacted.
META_PER_CLIENT_PAYLOADS = "_PER_CLIENT_PAYLOADS_"

# PQC routing: keys for key-exchange data attached to KeyGen workflow
KEY_PQC_PUBLIC_KEY = "pqc_public_key"
KEY_CLIENT_PQC_PUBLIC_KEYS = "client_pqc_public_keys"
KEY_PQC_KEY_PACKAGES = "pqc_key_packages"
KEY_PQC_KEY_PACKAGE = "pqc_key_package"

class HEAggregator(Aggregator):
    """
    An NVFlare Aggregator for orchestrating Homomorphic Encryption (HE) workflows.

    This aggregator manages the server-side logic for complex, multi-round HE
    operations, such as distributed key generation and multi-party decryption.
    It acts as a central coordinator, collecting data from clients (e.g., key shares,
    partial decryptions) and using the OpenfheManager to perform the necessary
    cryptographic aggregations.

    The `aggregate` method serves as the main entry point and routes tasks based
    on the current workflow name provided by the NVFlare controller.
    """
    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def __init__(self):
        """
        Initializes the HEAggregator.
        """
        super().__init__()
        self.openfhe_manager = OpenfheManager()
        # A dictionary to store data received from clients in the current round.
        # Key: client name, Value: client's submitted data (dxo.data).
        self.accepted_data = {}
        self.secret_key = None

        # Stores the server's local list of encrypted results, which is needed
        # as input for the multi-party decryption workflow.
        self.local_list_enc_result = None

        self.arch = None
        self.hide_result_from_server = None

        self.custom_logger = logging.getLogger("custom.audit_log")


    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        """
        The main entry point for the aggregator, called once per round by the NVFlare controller.

        This method acts as a router, dispatching tasks to the appropriate handler
        based on the `workflow_name` property from the FLContext.

        Args:
            fl_ctx: The FLContext containing the state of the federated learning environment.

        Returns:
            A Shareable object containing the aggregated results to be sent back to clients
            or to the persistor.
        """
        workflow_name = fl_ctx.get_prop(ReservedKey.WORKFLOW)
        round_result = None
        if workflow_name == "init_mix_SAG":
            round_result = self.get_shareable_data({}, fl_ctx, metadata={})
        elif workflow_name == "workflow_KeyGen":
            if fl_ctx.get_prop(AppConstants.CURRENT_ROUND) == 0:
                self.arch = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']['arch']
                self.hide_result_from_server = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)['meta']['hide_result_from_server']
            round_result = self._workflow_KeyGen(fl_ctx)
        else:
            return round_result # Don't reset if workflow not handled by parent class
        self.reset(fl_ctx)
        return round_result

    def set_sk(self, sk):
        '''Sets the server's secret key, typically provided by the Persistor during KeyGen.'''
        self.secret_key = sk


    # ------------------------------------------------------------------
    # Workflow: KeyGen
    # ------------------------------------------------------------------
    def _workflow_KeyGen(self, fl_ctx: FLContext):
        """
        Handles the server-side logic for the multi-round key generation workflow.

        This method orchestrates the aggregation of key materials from clients
        based on the selected architecture ('star' or 'cc').

        Args:
            fl_ctx: The FLContext for the current round.

        Returns:
            A Shareable containing the aggregated key materials for the next round.
        """
        round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        global_model = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)
        workspace_root = fl_ctx.get_prop(ReservedKey.WORKSPACE_ROOT)

        leader_client_name = (global_model.get("meta") or {}).get("leader_client_name", "site1")

        if self.arch == "star":
            if round == 0:
                # Round 0: Aggregate public key shares and initial eval key shares from all clients.
                for site, value in self.accepted_data.items():
                    if global_model['weights'].get('evalMultKey') is not None and value.get("evalMultKey2", None) == None:
                            self.custom_logger.warning(f"Missing mult key share from {site}.")
                    if global_model['weights'].get('evalSumKeys') is not None and value.get("evalSumKeysB", None) == None:
                            self.custom_logger.warning(f"Missing sum key share from {site}.")
                    if global_model['weights'].get('evalAtIndexKeys') is not None and value.get("evalAtIndexKeysB", None) == None:
                            self.custom_logger.warning(f"Missing index key share from {site}.")
                self.custom_logger.info(f"RECV: All clients key-shares of public key{f', mult key' if global_model['weights'].get('evalMultKey') is not None else ''}{f', sum key' if global_model['weights'].get('evalSumKeys') is not None else ''}{f', index key' if global_model['weights'].get('evalAtIndexKeys') is not None else ''}.")
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_weights = self.openfhe_manager.aggregate_keygen_star_round0(global_model, self.accepted_data, workspace_root, self.secret_key)
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
                # PQC routing: send other clients' public keys only to lead client (for hide_result_from_server).
                if self.hide_result_from_server:
                    client_pqc_public_keys = {
                        name: data[KEY_PQC_PUBLIC_KEY]
                        for name, data in self.accepted_data.items()
                        if name != leader_client_name and data.get(KEY_PQC_PUBLIC_KEY) is not None
                    }
                    per_client_specs = {
                        leader_client_name: {"_extra_data_": {KEY_CLIENT_PQC_PUBLIC_KEYS: client_pqc_public_keys}}
                    }
                    # Pass leader_client_name in meta so round 1 still has it (round 1 global_model is this result)
                    return self.get_shareable_data_asymmetric(
                        ser_weights,
                        {"round": round + 1, "leader_client_name": leader_client_name},
                        per_client_specs,
                        fl_ctx,
                    )
                self.custom_logger.info(f"SEND: to all clients: Multi-party public key{f' and partial mult key' if 'evalMultAB' in ser_weights else ''}.")
                return self.get_shareable_data(ser_weights, fl_ctx, metadata={"round": round + 1})
            elif round == 1:
                # Round 1: Aggregate final evaluation key shares to create the complete keys.
                if self.openfhe_manager.generate_mult_keys == True:
                    for site, value in self.accepted_data.items():
                        if value.get("evalMultBAB", None) == None:
                            self.custom_logger.warning(f"Missing mult key share from {site}.")
                    self.custom_logger.info(f"RECV: All clients key-shares of mult keys.")
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_cc = self.openfhe_manager.aggregate_keygen_star_round1(self.accepted_data)
                    ser_weights = {"CC": ser_cc}
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
                # PQC routing: include key packages from lead client for persistor to save.
                if self.hide_result_from_server:
                    lead_data = self.accepted_data.get(leader_client_name) or {}
                    pqc_key_packages = lead_data.get(KEY_PQC_KEY_PACKAGES)
                    if pqc_key_packages:
                        ser_weights[KEY_PQC_KEY_PACKAGES] = pqc_key_packages
            else:
                raise Exception(f"Invalid round {round}")
        elif self.arch == "cc":
            if round == 0:
                # Round 0: Receive the initial CC and keys from the 'leader' client.
                self.custom_logger.info("KeyGen Round 0: Receiving initial CC and keys from the leader.")
                if (len(fl_ctx.get_engine().all_clients) <= 1):
                    self.openfhe_manager.is_MultiParty = False
                    self.custom_logger.info("Single client detected. Disabling multi-party features.")
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_weights = self.openfhe_manager.aggregate_keygen_cc_round0(self.accepted_data, workspace_root)
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            elif round == 1:
                # Round 1: Aggregate key shares from all non-leader clients.
                self.custom_logger.info("KeyGen Round 1: Aggregating key shares from non-leader clients.")
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_weights = self.openfhe_manager.aggregate_keygen_cc_round1(self.accepted_data, workspace_root)
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            elif round == 2:
                # Round 2: Aggregate final evaluation key shares to create the complete keys.
                self.custom_logger.info("KeyGen Round 2: Aggregating final eval key shares.")
                self.fire_event(StatAnalyticsEventType.COMPUTE_START, fl_ctx)
                try:
                    ser_cc = self.openfhe_manager.aggregate_keygen_star_round1(self.accepted_data)
                    ser_weights = {"CC": ser_cc}    # CC shared to persistor to save
                finally:
                    self.fire_event(StatAnalyticsEventType.COMPUTE_END, fl_ctx)
            else:
                raise Exception(f"Invalid round {round}")
        else:
            raise Exception(f"Unsupported architecture '{self.arch}'")

        return self.get_shareable_data(ser_weights, fl_ctx, metadata={"round": round+1})


    # ------------------------------------------------------------------
    # Workflow: Decryption
    # ------------------------------------------------------------------
    def _Decryption_r0(self, fl_ctx):
        """
        Handles the server's role in the multi-party decryption workflow.

        This method collects partial decryption shares from all clients and uses
        the OpenFHE manager to fuse them with its own share, reconstructing the
        final plaintext result.

        Args:
            fl_ctx: The FLContext for the current round.

        Returns:
            A Shareable containing the final decrypted result.
        """
        round = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        total_rounds = fl_ctx.get_prop(AppConstants.NUM_ROUNDS)
        self.custom_logger.info(f"Executing multi-party decryption, combining {len(self.accepted_data)} client shares.")

        # The manager fuses the server's local encrypted data with client shares.
        self.fire_event(StatAnalyticsEventType.DECRYPT_START, fl_ctx)
        try:
            ser_weights = self.openfhe_manager.server_decrypt_round0(
                accepted_data=self.accepted_data,
                local_list_enc_result=self.local_list_enc_result
            )
        finally:
            self.fire_event(StatAnalyticsEventType.DECRYPT_END, fl_ctx)

        # Add metadata to indicate if this is the final round of the job.
        if round+1 == total_rounds-1:
            return self.get_shareable_data({"result": ser_weights}, fl_ctx, metadata={"round": round+1, "is_final_round": True})
        return self.get_shareable_data({"result": ser_weights}, fl_ctx, metadata={"round": round+1})


    # ------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------

    def accept(self, shareable: Shareable, fl_ctx: FLContext) -> bool:
        """
        Called by NVFlare to accept a Shareable contribution from a client.

        This method validates the incoming Shareable, checks its return code,
        and stores the data in `self.accepted_data` keyed by the contributor's name.

        Args:
            shareable: The Shareable object received from a client.
            fl_ctx: The current FLContext.

        Returns:
            A boolean indicating if the contribution was accepted.
        """
        contributor_name = shareable.get_peer_prop(key=ReservedKey.IDENTITY_NAME, default="?")

        rc = shareable.get_return_code()
        if rc and rc != ReturnCode.OK:
            self.log_warning(fl_ctx, f"Contributor {contributor_name} returned rc: {rc}. Disregarding contribution.")
            return False

        try:
            dxo = from_shareable(shareable)
        except Exception:
            self.log_exception(fl_ctx, "shareable data is not a valid DXO")
            return False
        if dxo.data_kind != DataKind.WEIGHTS:
            self.log_exception(fl_ctx, "expecting DataKind.WEIGHTS")
            return False

        # For profiling: accumulate incoming payload size
        fl_ctx.set_prop("__prof_payload_in_acc",
            fl_ctx.get_prop("__prof_payload_in_acc", 0) + len(shareable.to_bytes()),
            sticky=True)

        if dxo.data and dxo.data != {}:
            self.accepted_data.update({contributor_name: dxo.data})

        return True

    def reset(self, fl_ctx: FLContext = None):
        '''Resets the `self.accepted_data` dictionary, typically at the end of an aggregation step.'''
        self.accepted_data = {}



    @staticmethod
    def get_shareable_data(data, fl_ctx: FLContext, metadata={}, target_clients = "@ALL") -> Shareable:
        """
        Creates a DXO of DataKind.WEIGHTS and converts it to a Shareable object.

        Args:
            data: The dictionary of data to be included in the DXO.
            fl_ctx: The FLContext, used here to get the client name for logging.
            metadata: The dictionary of metadata for the DXO.
            target_clients: Specifies the target clients for the Shareable. Defaults to "@ALL".

        Returns:
            A Shareable object ready to be sent.
        """
        if target_clients is not None and target_clients != "@ALL":
            metadata["_TARGET_CLIENTS_"] = target_clients
        dxo = DXO(data_kind=DataKind.WEIGHTS, data=data, meta=metadata)
        shareable = dxo.to_shareable()
        # For profiling: accumulate outgoing payload size
        fl_ctx.set_prop("__prof_payload_out_acc",
            fl_ctx.get_prop("__prof_payload_out_acc", 0) + len(shareable.to_bytes()),
            sticky=True)
        return shareable

    # ------------------------------------------------------------------
    # Asymmetric payloads (per-client data + metadata)
    # ------------------------------------------------------------------

    @staticmethod
    def get_shareable_data_asymmetric(
        base_data: Dict[str, Any],
        base_metadata: Dict[str, Any],
        per_client_specs: Dict[str, Optional[Dict[str, Any]]],
        fl_ctx: FLContext,
        data_kind=DataKind.WEIGHTS,
    ) -> Shareable:
        """
        Builds a single Shareable that encodes a base payload plus per-client overrides.
        The workflow will send each client the appropriate payload (base, base+extra, or override)
        without duplicating the base data in memory for clients that get the same payload.

        Per-client spec (value in per_client_specs):
          - None or {} or absent: client receives base data + base metadata (no copy of base).
          - {"_extra_data_": dict, "_extra_meta_": dict}: client receives base merged with extra
            (only one merged copy is created per such client).
          - {"_override_": True, "data": dict, "meta": dict}: client receives only this data/meta
            (no base; useful for "no work" or client-specific-only payloads).

        Args:
            base_data: Shared data dict for all clients that get the base (or base+extra).
            base_metadata: Shared metadata dict for the base payload.
            per_client_specs: Map client_name -> spec (None / extra / override).
            fl_ctx: FLContext for profiling.
            data_kind: DXO data kind (default WEIGHTS).

        Returns:
            Shareable with data=base_data, meta=base_metadata + {META_PER_CLIENT_PAYLOADS: per_client_specs}.

        Example (same base for all, extra for one client):
            base_data, base_meta = {"weights": ...}, {"round": 1}
            per_client = {"site-1": {"_extra_meta_": {"role": "leader"}}}  # site-2, site-3 get base only
            return HEAggregator.get_shareable_data_asymmetric(base_data, base_meta, per_client, fl_ctx)

        Example (same for all except one client gets empty / no work):
            per_client = {"site-2": {"_override_": True, "data": {}, "meta": {"round": 1, "skip": True}}}
        """
        meta = dict(base_metadata)
        meta[META_PER_CLIENT_PAYLOADS] = per_client_specs
        dxo = DXO(data_kind=data_kind, data=base_data, meta=meta)
        shareable = dxo.to_shareable()
        fl_ctx.set_prop(
            "__prof_payload_out_acc",
            fl_ctx.get_prop("__prof_payload_out_acc", 0) + len(shareable.to_bytes()),
            sticky=True,
        )
        return shareable
