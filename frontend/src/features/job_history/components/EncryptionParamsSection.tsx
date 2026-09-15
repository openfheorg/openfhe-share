import AbstractAccordion from "../../../components/AbstractAccordion";
import { NVFlareJob } from "../../../types/JobsDataTypes";

interface EncryptionParamsSectionProps {
    job: NVFlareJob;
    jobKey: string;
    isOpen: boolean;
    onToggle: () => void;
}

export default function EncryptionParamsSection({
    job,
    jobKey,
    isOpen,
    onToggle
}: EncryptionParamsSectionProps) {
    return (
        <AbstractAccordion
            title="Encryption Parameters"
            titleTooltip="Show/Hide Encryption Parameters"
            isOpen={isOpen}
            onToggle={onToggle}
            stopPropagation={true}
            containerStyle={{ padding: "5px 0" }}
            bodyStyle={{
                border: "1px solid black",
                marginTop: "5px",
                padding: "0.75rem 1rem",
                fontSize: 12
            }}
        >
            {job.crypto_audit_record ? (
                <div>
                    <div
                        className="encryption-params-section-block-01"
                    > <div>Security Level:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.security_level}</div>
                        <div>Ring Dimension:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.ring_dimension}</div>
                        <div>Batch Size:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.batch_size}</div>
                        <div>Scale Mod Size:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.scale_mod_size}</div>
                        <div>Multiplicative Depth:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.multiplicative_depth}</div>
                        <div>Scaling Technique:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.scaling_technique}</div>
                        <div>KeySwitch Technique:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.keyswitch_technique}</div>
                        <div>CKKS Data Type:</div>
                        <div className="duality-font-semibold">{job.crypto_audit_record.ckks_data_type}</div>
                        <div>IND-CPA^D noise flooding bits:</div>
                        <div className="duality-font-semibold">
                            {job.crypto_audit_record.ind_cpa_noise_bits} bits (default)
                        </div>
                        <div>Audit created at:</div>
                        <div className="duality-font-semibold">
                            {job.crypto_audit_record.created_at || "Not recorded"}
                        </div>
                    </div>
                </div>
            ) : (
                <div className="duality-text-64748b-fs-12px">
                    No CryptoContext audit record available for this job.
                </div>
            )}
        </AbstractAccordion>
    );
}
