import React from "react";
import AbstractModal from "../../../components/AbstractModal";

interface ColumnConfigModalProps {
    isOpen: boolean;
    onClose: () => void;
    availableKeys: string[];
    selectedKeys: string[];
    onChangeSelectedKeys: (keys: string[]) => void;
}

const prettyLabel = (key: string): string => {
    return String(key || "")
        .replace(/-/g, "_")
        .toLowerCase()
        .split("_")
        .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : ""))
        .join(" ");
};

const ColumnConfigModal: React.FC<ColumnConfigModalProps> = ({
    isOpen,
    onClose,
    availableKeys,
    selectedKeys,
    onChangeSelectedKeys
}) => {
    const picked = (selectedKeys || []).slice(0, 3);

    return (
        <AbstractModal
            isOpen={isOpen}
            title="Configure Analysis History Table Columns"
            ariaLabel="Configure columns modal"
            onClose={onClose}
            width="min(720px, 96vw)"
            bodyStyle={{ padding: "12px 12px 14px 12px" }}
            titleStyle={{ fontSize: "16pt", marginLeft: "1rem", color: "#3F5FFF", fontWeight: 700, width: "100%" }}
        >
            <div className="column-config-modal-block-01">
                Default columns (Job, Analysis Functions, Status, Created) are always shown. Select up to 3 extra columns from available function configuration fields.
            </div>

            {availableKeys.length === 0 ? (
                <div className="column-config-modal-block-02">
                    No additional function configuration fields are available in the current analysis history response.
                </div>
            ) : (
                <>
                    <div
                        className="column-config-modal-block-03"
                    >
                        <div className="column-config-modal-block-04">
                            Available fields ({availableKeys.length})
                        </div>
                        <div className="column-config-modal-block-05">
                            Selected: {Math.min(3, picked.length)} / 3
                        </div>
                    </div>

                    <div
                        className="column-config-modal-block-06"
                    >
                        {availableKeys.map((k) => {
                            const checked = picked.includes(k);
                            const disableNewPick = !checked && picked.length >= 3;

                            return (
                                <label
                                    key={k}
                                    className="column-config-modal-block-07" style={{ opacity: disableNewPick ? 0.55 : 1 }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={checked}
                                        disabled={disableNewPick}
                                        onChange={(e) => {
                                            const nextChecked = e.target.checked;
                                            if (nextChecked) {
                                                if (picked.includes(k)) {
                                                    onChangeSelectedKeys(picked.slice(0, 3));
                                                    return;
                                                }
                                                onChangeSelectedKeys([...picked, k].slice(0, 3));
                                                return;
                                            }
                                            onChangeSelectedKeys(picked.filter((x) => x !== k).slice(0, 3));
                                        }}
                                    />
                                    <div className="duality-d-flex-col-column">
                                        <div className="duality-font-semibold">{prettyLabel(k)}</div>
                                        <div className="column-config-modal-block-08">{k}</div>
                                    </div>
                                </label>
                            );
                        })}
                    </div>

                    <div className="column-config-modal-block-09">
                        <button
                            className="secondary-button column-config-modal-shared-01"
                            onClick={() => onChangeSelectedKeys([])}
                            
                            title="Clear selection"
                        >
                            Clear
                        </button>
                        <button
                            onClick={onClose}
                            className="column-config-modal-shared-01"
                            title="Done"
                        >
                            Done
                        </button>
                    </div>
                </>
            )}
        </AbstractModal>
    );
};

export default ColumnConfigModal;
